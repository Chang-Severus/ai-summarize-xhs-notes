# -*- coding: utf-8 -*-
"""
自动发布到 GitHub Pages（多收藏夹）
=================================

遍历 config.collections 里所有收藏夹，把每个收藏夹的网页同步到 docs/<id>/，
并生成一个总导航页 docs/index.html（列出所有主题，点击进入各自子页）。
然后 git add / commit / push 到 GitHub。

GitHub Pages 配置为 main 分支 /docs 目录发布后：
  - 总导航： https://用户名.github.io/仓库名/
  - 各主题： https://用户名.github.io/仓库名/<id>/

用法（通常由 summarize.py 自动调用；也可手动）：
  python scraper/publish.py

依赖 config.json 的 publish 配置块：
  { "publish": { "enabled": true, "auto": true,
                 "repo_url": "git@github.com:用户名/仓库名.git", "branch": "main" } }
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTIONS_DIR = ROOT / "collections"
DOCS_DIR = ROOT / "docs"
CONFIG_PATH = ROOT / "config.json"
WEB_TEMPLATE = ROOT / "output" / "index.html"   # 网页模板


def run(cmd: list):
    """运行命令，返回 (是否成功, 输出)。成功与否严格依据返回码。"""
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return (r.returncode == 0), (r.stdout or "") + (r.stderr or "")


def build_index_page(collections: list) -> str:
    """生成总导航页 HTML：卡片式列出所有收藏夹。"""
    cards = ""
    for c in collections:
        cid = c["id"]
        name = c.get("name", cid)
        # 读取该收藏夹的知识点数量（若有 summary.json）
        sj = COLLECTIONS_DIR / cid / "output" / "summary.json"
        count_txt = ""
        if sj.exists():
            try:
                s = json.load(open(sj, encoding="utf-8"))
                npt = sum(len(t.get("points", [])) for t in s.get("topics", []))
                ntp = len(s.get("topics", []))
                count_txt = f"{ntp} 个主题 · {npt} 条知识点"
            except Exception:
                pass
        cards += f"""
      <a class="card" href="./{cid}/index.html">
        <div class="card-name">{name}</div>
        <div class="card-meta">{count_txt or '尚未生成总结'}</div>
        <div class="card-go">进入 →</div>
      </a>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>我的小红书知识库</title>
<style>
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;
         background:#f7f7f8; color:#1f2329; }}
  header {{ background:linear-gradient(135deg,#ff2442,#ff6b81); color:#fff; padding:36px 24px; }}
  header h1 {{ margin:0 0 6px; font-size:24px; }}
  header p {{ margin:0; opacity:.92; font-size:14px; }}
  .wrap {{ max-width:920px; margin:0 auto; padding:24px 20px 60px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px; }}
  .card {{ display:block; background:#fff; border:1px solid #e8e9ec; border-radius:14px;
           padding:20px; text-decoration:none; color:inherit;
           box-shadow:0 1px 3px rgba(0,0,0,.06); transition:.15s; }}
  .card:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,0,0,.1); border-color:#ff2442; }}
  .card-name {{ font-size:17px; font-weight:700; margin-bottom:8px; }}
  .card-meta {{ font-size:13px; color:#646a73; margin-bottom:14px; }}
  .card-go {{ font-size:13px; color:#ff2442; font-weight:600; }}
  footer {{ text-align:center; color:#999; font-size:12px; padding:20px; }}
</style>
</head>
<body>
<header>
  <div class="wrap" style="padding-bottom:0;">
    <h1>我的小红书知识库</h1>
    <p>按主题收藏夹整理的知识点总结 · 点击进入查看</p>
  </div>
</header>
<div class="wrap">
  <div class="grid">{cards}
  </div>
</div>
<footer>由小红书收藏夹 AI 总结工具自动生成</footer>
</body>
</html>"""


def sync_all_collections(cfg: dict):
    """把每个收藏夹的网页同步到 docs/<id>/，并生成总导航页。"""
    DOCS_DIR.mkdir(exist_ok=True)
    collections = cfg.get("collections", []) or []
    published = []
    for c in collections:
        cid = c["id"]
        out = COLLECTIONS_DIR / cid / "output"
        summary = out / "summary.json"
        if not summary.exists():
            print(f"  [跳过] 收藏夹 {cid} 还没有 summary.json（未生成总结）")
            continue
        dst = DOCS_DIR / cid
        dst.mkdir(parents=True, exist_ok=True)
        # 网页：优先用该收藏夹自己的 index.html，没有则用模板
        src_html = out / "index.html"
        if not src_html.exists() and WEB_TEMPLATE.exists():
            src_html = WEB_TEMPLATE
        shutil.copy(src_html, dst / "index.html")
        shutil.copy(summary, dst / "summary.json")
        published.append(c)
        print(f"  已同步收藏夹 [{cid}] 到 docs/{cid}/")

    # 生成总导航页
    if published:
        (DOCS_DIR / "index.html").write_text(build_index_page(published), encoding="utf-8")
        print(f"已生成总导航页 docs/index.html（{len(published)} 个收藏夹）")
    return published


def publish(cfg: dict) -> bool:
    pub = (cfg or {}).get("publish", {}) or {}
    if not pub.get("enabled"):
        print("config.json 未启用 publish（enabled=false），跳过发布。")
        return False
    repo_url = pub.get("repo_url", "").strip()
    branch = pub.get("branch", "main")
    if not repo_url or "用户名" in repo_url:
        print("[!] 请先在 config.json 的 publish.repo_url 填写你的 GitHub 仓库地址"
              "（推荐 SSH 格式：git@github.com:用户名/仓库名.git）。")
        return False

    print("同步所有收藏夹网页到 docs/ ...")
    published = sync_all_collections(cfg)
    if not published:
        print("没有可发布的收藏夹（都还没生成 summary.json）。")
        return False

    # 初始化 git（若未初始化）
    if not (ROOT / ".git").exists():
        run(["git", "init"])
        run(["git", "branch", "-M", branch])

    # 设置/更新远程地址（严格判断 origin 是否存在）
    ok, _ = run(["git", "remote", "get-url", "origin"])
    if ok:
        run(["git", "remote", "set-url", "origin", repo_url])
    else:
        run(["git", "remote", "add", "origin", repo_url])

    # 提交并推送
    run(["git", "add", "."])
    msg = f"update: 知识点总结 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ok, out = run(["git", "commit", "-m", msg])
    if not ok and "nothing to commit" in out:
        print("内容无变化，无需提交。")
    ok, out = run(["git", "push", "-u", "origin", branch])
    if not ok:
        print("[X] 推送失败：")
        print(out[:500])
        print("\n常见原因：① SSH key 未添加到 GitHub；② 仓库地址错误；③ 远程已有内容需先 pull。")
        return False

    print("✅ 已推送到 GitHub。若已配置 Pages(main/docs)，稍等 1~2 分钟即可看到更新。")
    return True


def main():
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8")) if CONFIG_PATH.exists() else {}
    publish(cfg)


if __name__ == "__main__":
    main()
