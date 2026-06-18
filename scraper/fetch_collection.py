# -*- coding: utf-8 -*-
"""
小红书收藏夹半自动抓取脚本
=========================

策略：用 Playwright 驱动真实浏览器 + 你的真实登录态，行为接近真人，最大程度规避风控。

流程：
  1. 首次运行：弹出浏览器，你扫码登录小红书。登录态会保存到 .auth/ 下，后续复用。
  2. 打开收藏夹页面，自动向下滚动加载所有帖子卡片，收集帖子链接。
  3. 逐条打开帖子，抓取标题/作者/正文/标签，并下载正文图片。
  4. 每条帖子输出为 data/notes/{note_id}.json，图片存到 data/images/。

注意：
  - 本脚本仅抓取“你自己已登录账号有权查看的收藏内容”，请合理控制频率，仅作个人学习使用。
  - 小红书前端 DOM 结构可能随版本变化，若某些字段抓不到，脚本会容错跳过并记录，不会中断整体流程。

用法：
  pip install -r requirements.txt
  python -m playwright install chromium
  cp config.example.json config.json   # 然后编辑 config.json
  python scraper/fetch_collection.py
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("缺少依赖 playwright，请先执行：pip install -r requirements.txt && python -m playwright install chromium")
    sys.exit(1)


sys.path.insert(0, str(Path(__file__).resolve().parent))
from collection_ctx import get_context  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录

# 以下目录在 main() 里会根据“当前收藏夹”重新赋值（多收藏夹隔离）。
# 登录态 .auth 是全局共用的（同一个小红书账号）。
AUTH_DIR = ROOT / ".auth"
NOTES_DIR = ROOT / "data" / "notes"
IMAGES_DIR = ROOT / "data" / "images"

# 从小红书帖子 URL 里提取帖子唯一 ID（note_id）的正则。
# 形如 /explore/65xxxx 或 /discovery/item/65xxxx，ID 是 16~32 位十六进制字符。
NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{16,32})")


def extract_note_id(url: str) -> str | None:
    m = NOTE_ID_RE.search(url or "")
    return m.group(1) if m else None


def already_fetched(note_id: str) -> bool:
    return (NOTES_DIR / f"{note_id}.json").exists()


def download_image(url: str, dest: Path, referer: str = "https://www.xiaohongshu.com/") -> bool:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": referer,
        }
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            return True
    except Exception as e:
        print(f"    [图片下载失败] {url[:60]}... {e}")
    return False


def is_logged_in(page) -> bool:
    """
    判断是否已登录：可靠依据是页面侧边栏的「登录」按钮是否存在。
    存在登录按钮 = 未登录；不存在 = 已登录。
    """
    try:
        # 小红书左侧导航的登录入口（多种兜底）
        login_btn = page.locator(
            "button:has-text('登录'), a:has-text('登录'), .login-btn, "
            ".side-bar :text('登录'), [class*='login']:has-text('登录')"
        )
        # 只要找到明显的“登录”可点击入口，就认为未登录
        return login_btn.count() == 0
    except Exception:
        return False


def login_if_needed(context, page):
    """检查登录态，未登录则等待用户【真正扫码登录】成功后才继续。"""
    page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
    time.sleep(4)

    if is_logged_in(page):
        print("已是登录状态，继续。")
        context.storage_state(path=str(AUTH_DIR / "state.json"))
        return

    print("\n" + "=" * 60)
    print("检测到【未登录】。请在弹出的浏览器窗口中扫码登录小红书。")
    print("（若没看到登录弹窗，点页面左下角的“登录”按钮）")
    print("脚本会每 3 秒检测一次，登录成功后自动继续，最多等待 300 秒。")
    print("=" * 60 + "\n")

    logged = False
    for i in range(100):  # 100 * 3s = 300s
        time.sleep(3)
        if is_logged_in(page):
            logged = True
            break
        if i % 5 == 0:
            print(f"  仍在等待登录... 已等待 {i*3} 秒")

    if not logged:
        print("[X] 超时仍未检测到登录。请重新运行脚本并完成扫码登录。")
        sys.exit(1)

    print("✅ 登录成功！正在保存登录态以便下次免登录...")
    time.sleep(2)
    context.storage_state(path=str(AUTH_DIR / "state.json"))


def collect_note_links(page, target_url: str, cfg: dict) -> list[dict]:
    """打开收藏夹页面，滚动加载，收集所有帖子链接。"""
    print(f"打开收藏夹页面：{target_url}")
    # 用 networkidle 等异步请求基本完成，再多等几秒，确保帖子卡片真正渲染出来
    page.goto(target_url, wait_until="networkidle")
    time.sleep(8)

    # 注意：不要在 board 收藏夹页点击任何“收藏”字样，否则可能误触发跳转离开本页。
    # 等待至少出现一个帖子链接（最多再等 20 秒），避免“加载未完成就开抓”
    for _ in range(10):
        if page.locator("a[href*='/explore/'], a[href*='/discovery/item/']").count() > 0:
            break
        time.sleep(2)

    max_notes = int(cfg.get("max_notes", 200))     # 最多收集多少条
    pause = float(cfg.get("scroll_pause_seconds", 2.5))  # 每次滚动后等待秒数（越大越像真人）

    seen = {}            # note_id -> url，用字典天然去重
    stable_rounds = 0    # 连续“没有新增帖子”的轮数
    last_count = 0       # 上一轮收集到的总数

    # 小红书收藏夹是“无限滚动”加载的：往下滚才会加载更多。
    # 这里循环：滚一屏 -> 把当前可见的帖子链接收集进 seen -> 再滚，直到没有新内容。
    print("开始滚动加载帖子卡片...")
    for i in range(200):  # 最多滚 200 次（足够上百条），防止异常时死循环
        # 抓取页面上所有指向帖子详情的链接
        anchors = page.locator("a[href*='/explore/'], a[href*='/discovery/item/']")
        n = anchors.count()
        for idx in range(n):
            try:
                href = anchors.nth(idx).get_attribute("href")
                if not href:
                    continue
                if href.startswith("/"):  # 相对链接补全成完整 URL
                    href = "https://www.xiaohongshu.com" + href
                nid = extract_note_id(href)
                if nid and nid not in seen:
                    seen[nid] = href
            except Exception:
                continue  # 单个链接出错不影响整体

        count = len(seen)
        print(f"  滚动第 {i+1} 轮，已收集 {count} 条帖子链接")

        # 退出条件1：已达到设定上限
        if count >= max_notes:
            print(f"  已达到上限 {max_notes} 条，停止滚动。")
            break

        # 退出条件2：连续 3 轮都没有新增，说明已经滚到底了
        if count == last_count:
            stable_rounds += 1
            if stable_rounds >= 3:
                print("  连续多轮无新增，认为已加载完所有帖子。")
                break
        else:
            stable_rounds = 0  # 有新增就重置计数
        last_count = count

        page.mouse.wheel(0, 3000)  # 向下滚动一屏
        time.sleep(pause)          # 等页面加载新内容

    # 只返回前 max_notes 条
    return [{"note_id": k, "url": v} for k, v in list(seen.items())[:max_notes]]


def collect_all_note_ids(page, cfg: dict) -> list[str]:
    """
    边滚动边收集所有帖子的 note_id。

    注意：小红书收藏夹用【虚拟滚动】——只渲染当前可见的卡片，滚过去的会从 DOM 移除，
    所以不能靠“DOM 里卡片数量”判断是否加载完，必须在滚动过程中把出现过的 id 都记下来。
    """
    max_notes = int(cfg.get("max_notes", 200))
    pause = float(cfg.get("scroll_pause_seconds", 2.5))
    seen = []          # 保持顺序的 note_id 列表
    seen_set = set()
    stable = 0         # 连续“无新增 id”的轮数
    print("滚动收集所有帖子 ID（收藏夹是虚拟滚动，需边滚边记）...")
    for i in range(300):
        # 收集当前可见卡片里隐藏 explore 链接的 note_id
        hrefs = page.eval_on_selector_all(
            "section.note-item a[href*='/explore/']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        before = len(seen_set)
        for h in hrefs or []:
            nid = extract_note_id(h or "")
            if nid and nid not in seen_set:
                seen_set.add(nid)
                seen.append(nid)
        print(f"  滚动第 {i+1} 轮，累计收集 {len(seen)} 个帖子 ID")

        if len(seen) >= max_notes:
            break
        # 连续若干轮没有新增 id，认为已滚到底
        if len(seen_set) == before:
            stable += 1
            if stable >= 5:
                print("  连续多轮无新增，认为已收集完所有帖子。")
                break
        else:
            stable = 0
        page.mouse.wheel(0, 2500)
        time.sleep(pause)

    return seen[:max_notes]


def find_item_by_note_id(page, note_id: str):
    """在当前页面（可能需要滚动）找到指定 note_id 的卡片 section。找不到返回 None。"""
    for _ in range(60):
        items = page.locator("section.note-item")
        n = items.count()
        for idx in range(n):
            try:
                href = items.nth(idx).locator("a[href*='/explore/']").first.get_attribute("href") or ""
                if note_id in href:
                    return items.nth(idx)
            except Exception:
                continue
        # 当前可见区域没找到，继续往下滚
        page.mouse.wheel(0, 2500)
        time.sleep(1.5)
    return None


def click_and_fetch_detail(page, item, note_id: str, cfg: dict):
    """
    点击某个帖子卡片(section.note-item)的封面，打开详情页抓取，抓完返回收藏夹。

    关键点：卡片里有两个 a 标签——
      - 隐藏的 <a href="/explore/...">（用于读 note_id，但 display:none 点不了）
      - 可见的 <a class="cover">（点它才会带上 xsec_token 进入详情，避免“无法浏览”）
    所以这里点击 a.cover。
    """
    try:
        cover = item.locator("a.cover").first
        cover.scroll_into_view_if_needed()
        cover.click()
        time.sleep(3)
    except Exception as e:
        print(f"    [点击失败] {note_id}: {str(e)[:80]}")
        return None

    # 点击后地址栏变成带 token 的详情 URL，记录下来作为溯源链接
    real_url = page.url
    detail = parse_detail_from_page(page, note_id, real_url, cfg)

    # 抓完返回收藏夹列表（详情是同标签页跳转，用浏览器后退最稳）
    try:
        page.go_back(wait_until="networkidle")
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    time.sleep(1.5)
    return detail


def parse_detail_from_page(page, note_id: str, url: str, cfg: dict) -> dict:
    """从【当前已打开的帖子详情页/浮层】抓取标题/正文/作者/标签/图片。"""
    # 小工具：按 CSS 选择器安全取文本，取不到返回空字符串（不报错）
    def safe_text(selector: str) -> str:
        try:
            loc = page.locator(selector).first
            if loc and loc.count() > 0:
                return (loc.inner_text() or "").strip()
        except Exception:
            pass
        return ""

    # 标题/正文/作者：小红书页面结构可能变，用 "A or B or C" 做多重兜底，
    # 哪个选择器能取到就用哪个，尽量不漏抓。
    title = safe_text("#detail-title") or safe_text(".title")
    desc = safe_text("#detail-desc") or safe_text(".note-text") or safe_text(".desc")
    author = safe_text(".author-wrapper .username") or safe_text(".username") or safe_text(".author")

    # 标签
    tags = []
    try:
        tag_loc = page.locator("a[href*='search_result'] , .tag")
        for i in range(min(tag_loc.count(), 30)):
            t = (tag_loc.nth(i).inner_text() or "").strip()
            if t.startswith("#") or len(t) <= 20:
                tags.append(t if t.startswith("#") else f"#{t}")
    except Exception:
        pass
    tags = list(dict.fromkeys([t for t in tags if t and t != "#"]))[:15]

    # 图片
    image_paths = []
    if cfg.get("download_images", True):
        try:
            imgs = page.locator(".note-slider img, .swiper-slide img, meta[property='og:image']")
            urls = []
            for i in range(min(imgs.count(), 12)):
                src = imgs.nth(i).get_attribute("src") or imgs.nth(i).get_attribute("content")
                if src and src.startswith("http") and "sns-img" in src or (src and src.startswith("http")):
                    urls.append(src)
            urls = list(dict.fromkeys(urls))
            for idx, iu in enumerate(urls[:9]):
                ext = ".jpg"
                dest = IMAGES_DIR / f"{note_id}_{idx}{ext}"
                if download_image(iu, dest, referer=url):
                    image_paths.append(str(dest.relative_to(ROOT)))
                time.sleep(0.3)
        except Exception as e:
            print(f"    [图片处理异常] {e}")

    data = {
        "note_id": note_id,
        "url": url,
        "title": title,
        "author": author,
        "publish_time": "",
        "text": desc,
        "image_ocr": [],   # 由 ocr_notes.py 填充
        "images": image_paths,
        "tags": tags,
    }
    return data


def main():
    # 解析 --collection 参数，拿到当前收藏夹的配置与隔离目录
    ctx = get_context()
    ctx.ensure_dirs()
    # 把模块级路径重设到当前收藏夹（下层函数都用这几个全局变量）
    global AUTH_DIR, NOTES_DIR, IMAGES_DIR
    AUTH_DIR = ctx.auth_dir
    NOTES_DIR = ctx.notes_dir
    IMAGES_DIR = ctx.images_dir

    target_url = ctx.board_url
    if not target_url:
        print(f"收藏夹 [{ctx.id}] 未配置 board_url，请在 config.json 的 collections 里填写。")
        return
    print(f"当前收藏夹：[{ctx.id}] {ctx.name}")

    headless = bool(ctx.get("headless", False))
    note_interval = float(ctx.get("note_interval_seconds", 4))
    cfg = ctx.coll  # 供 collect_all_note_ids 等读取 max_notes / scroll_pause_seconds
    # 让滚动/上限参数也能回退到全局
    for k in ("max_notes", "scroll_pause_seconds"):
        if k not in cfg:
            cfg[k] = ctx.cfg.get(k, {"max_notes": 200, "scroll_pause_seconds": 2.5}[k])
    cfg["download_images"] = ctx.get("download_images", True)

    with sync_playwright() as p:
        state_path = AUTH_DIR / "state.json"   # 登录态文件
        launch_args = dict(headless=headless)
        browser = p.chromium.launch(**launch_args)
        # 如果之前已登录过（存在 state.json），直接带着登录态打开，免重复扫码；
        # 否则开一个全新的浏览器上下文，稍后引导用户扫码。
        if state_path.exists():
            context = browser.new_context(storage_state=str(state_path))
        else:
            context = browser.new_context()
        context.set_default_timeout(20000)  # 元素查找默认超时 20 秒
        page = context.new_page()

        # 1. 登录
        login_if_needed(context, page)

        # 2. 打开收藏夹并滚动加载，让所有帖子卡片渲染出来
        print(f"打开收藏夹页面：{target_url}")
        page.goto(target_url, wait_until="networkidle")
        time.sleep(8)
        for _ in range(10):
            if page.locator("section.note-item").count() > 0:
                break
            time.sleep(2)

        # 3. 先边滚边收集全部帖子 ID（应对虚拟滚动）
        note_ids = collect_all_note_ids(page, cfg)
        print(f"\n共收集到 {len(note_ids)} 个帖子 ID，开始逐条点击抓取...\n")

        # 4. 逐个 ID：滚回顶部 -> 找到该卡片 -> 点击封面进详情抓取 -> 返回
        #    （点击进入才会带 xsec_token，避免“当前笔记暂时无法浏览”）
        ok, skip, fail = 0, 0, 0
        total = len(note_ids)
        for i, nid in enumerate(note_ids):
            if already_fetched(nid):
                skip += 1
                print(f"[{i+1}/{total}] {nid} 已抓取过，跳过")
                continue

            # 回到收藏夹顶部，重新定位目标卡片（虚拟滚动下卡片会被回收，需重新找）
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1.5)
            item = find_item_by_note_id(page, nid)
            if item is None:
                fail += 1
                print(f"[{i+1}/{total}] {nid} 未在列表中找到，跳过")
                continue

            print(f"[{i+1}/{total}] 点击抓取 {nid} ...")
            detail = click_and_fetch_detail(page, item, nid, cfg)
            if detail and detail.get("title") and "无法浏览" not in detail["title"]:
                with open(NOTES_DIR / f"{nid}.json", "w", encoding="utf-8") as f:
                    json.dump(detail, f, ensure_ascii=False, indent=2)
                ok += 1
                print(f"    OK：{detail['title'][:30]} | 图片 {len(detail['images'])} 张")
            else:
                fail += 1
                print(f"    [失败/无法浏览] {nid}")
            time.sleep(note_interval)

        # 更新登录态
        context.storage_state(path=str(state_path))
        browser.close()

        print(f"\n抓取完成：新增 {ok} 条，跳过 {skip} 条，失败 {fail} 条。")
        print(f"帖子数据在：{NOTES_DIR}")
        print(f"接下来执行：python scraper/ocr_notes.py  对图片做 OCR。")


if __name__ == "__main__":
    main()
