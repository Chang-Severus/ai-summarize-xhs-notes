# -*- coding: utf-8 -*-
"""
知识点总结脚本（可选的 API 自动化方案）
=====================================

把 data/notes/*.json 自动跑成知识点总结，输出：
  - output/summary.json   （结构化，带原帖溯源，供网页读取）
  - output/知识点总结.md   （人类可读）

【两种总结方式，二选一】
  方式A（默认推荐）：不用本脚本，直接在对话里让 Claude 帮你总结，质量最高、0 API 成本。
  方式B（本脚本）  ：用 API 自动跑，适合帖子特别多 / 想全自动。模型可在 config.json 切换。

启用方式B：在 config.json 的 summarization 里填好 base_url/model/api_key（推荐 Claude Sonnet），
然后运行：
  python scraper/summarize.py

流程严格复用 prompts/summarize_prompt.md 的策略：
  1) 逐条提炼知识点 + 质量评级（强制带 note_id 溯源，不臆造）
  2) 汇总：按主题归类、合并重复点但保留所有来源

【增量更新】
  每条帖子的提炼结果缓存在 data/extracted/{note_id}.json。
  再次运行时只对“没有缓存的新帖”调用模型，旧帖直接复用缓存，
  最后把全部提炼结果（新+旧）一起做汇总归类输出。
  => 收藏夹新增帖子后，重跑全流程即可，只会分析新帖，不重复花钱。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 这几个目录在 main() 里按当前收藏夹重设（多收藏夹隔离）
NOTES_DIR = ROOT / "data" / "notes"
EXTRACTED_DIR = ROOT / "data" / "extracted"
OUTPUT_DIR = ROOT / "output"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers.text_llm_provider import TextLLMProvider  # noqa: E402
from collection_ctx import get_context  # noqa: E402


# ============================================================
# 提示词常量：分两个阶段
#   阶段1（EXTRACT）：逐条帖子 -> 提炼知识点 + 评级 + 带溯源
#   阶段2（MERGE）  ：把所有提炼结果汇总 -> 按主题归类 + 合并重复
# 想调整总结风格/规则，主要改这两段提示词即可。
# ============================================================

# 阶段1 的系统提示：约束模型只输出 JSON
SYSTEM_EXTRACT = "你是一个严谨的技术知识提炼助手，只输出 JSON，不输出任何多余文字。"

# 阶段1 的用户提示：{batch} 会被替换成本批帖子的 JSON
PROMPT_EXTRACT = """下面是若干条小红书技术帖子（关于 AI/LLM/Agent）。请为每条帖子提炼核心知识点。

【严格要求】
1. 只总结帖子里实际出现的内容，不要补充你自己的知识，不要臆造。
2. 每个知识点：point（一句话讲清重点）+ detail（1~3句关键说明/结论）。
3. 给每条帖子整体打质量评级 quality：
   high=有具体方法/结论/数据值得细看；medium=有信息量但不突出；low=空泛/营销/常识/无实质。
4. 每条必须带 source_note_id / source_url / source_title，取自给定数据，不得修改或编造。
5. 没有价值知识点的帖子，points 输出 []，quality 标 low。

【只输出 JSON 数组】，每元素对应一条帖子：
[{{"source_note_id":"...","source_url":"...","source_title":"...","quality":"high|medium|low",
"topic_hint":"如 RAG/Agent/微调/Prompt工程/向量数据库/多模态/工程部署/评测 等",
"points":[{{"point":"...","detail":"..."}}]}}]

【帖子数据】
{batch}
"""

# 阶段2 的系统提示
SYSTEM_MERGE = "你是一个严谨的知识整理助手，只输出 JSON，不输出任何多余文字。"

# 阶段2 的用户提示：{extracted} 会被替换成阶段1 所有提炼结果
PROMPT_MERGE = """下面是逐条提炼出的知识点（JSON 数组）。请汇总整理。

【要求】
1. 按主题 topic 聚类归并，主题示例：Prompt工程/RAG检索增强/Agent设计/模型微调与训练/
   向量数据库/多模态/推理优化与部署/评测与可观测/工具与框架/行业应用/其他。
2. 合并语义重复的知识点，但保留所有来源（多个 source 都列出）。
3. 每个知识点 quality 取来源中最高者。
4. 不丢失任何 high/medium 知识点；low 单独归到“低质量/可跳过”。
5. 主题内按重要性（被提及次数、质量）从高到低排序。

【只输出如下 JSON】：
{{"topics":[{{"topic":"主题名","points":[{{"point":"...","detail":"...","quality":"high|medium|low",
"sources":[{{"note_id":"...","url":"...","title":"..."}}]}}]}}]}}

【逐条提炼结果】
{extracted}
"""


def parse_json_loose(text: str):
    """
    从模型输出里稳健地解析 JSON。
    claude-opus 等模型常见问题：① 用 ```json 包裹；② 前后带解释文字；
    ③ 输出多个代码块。这里做多层兜底，尽量不丢内容。
    """
    if not text:
        raise ValueError("模型返回为空")
    t = text.strip()

    # 1) 优先提取 ```json ... ``` 或 ``` ... ``` 代码块里的内容
    fences = re.findall(r"```(?:json)?\s*(.*?)```", t, flags=re.DOTALL)
    candidates = [f.strip() for f in fences if f.strip()]
    # 2) 再把整段（去掉可能残留的围栏）也作为候选
    stripped = re.sub(r"^```(json)?", "", t).strip()
    stripped = re.sub(r"```$", "", stripped).strip()
    candidates.append(stripped)
    candidates.append(t)

    # 逐个候选尝试直接解析
    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            pass

    # 3) 兜底：在所有候选里截取最外层 [..] 或 {..} 再解析
    for c in candidates:
        for l, r in (("[", "]"), ("{", "}")):
            i, j = c.find(l), c.rfind(r)
            if i != -1 and j != -1 and j > i:
                frag = c[i:j + 1]
                try:
                    return json.loads(frag)
                except Exception:
                    # 4) 再兜底：去掉对象间可能多余的尾逗号
                    try:
                        return json.loads(re.sub(r",\s*([\]}])", r"\1", frag))
                    except Exception:
                        continue
    raise ValueError("无法解析模型返回的 JSON")


def local_merge(extracted_all: list) -> dict:
    """
    本地兜底汇总（不调模型）：当模型汇总失败/超时时使用。
    按每条提炼结果自带的 topic_hint 归类，保留所有知识点与来源，绝不让网页空白。
    """
    topics = {}
    for item in extracted_all:
        topic = (item.get("topic_hint") or "未分类").strip() or "未分类"
        src = {
            "note_id": item.get("source_note_id", ""),
            "url": item.get("source_url", ""),
            "title": item.get("source_title", ""),
        }
        quality = item.get("quality", "medium")
        for p in item.get("points", []):
            topics.setdefault(topic, []).append({
                "point": p.get("point", ""),
                "detail": p.get("detail", ""),
                "quality": quality,
                "sources": [src],
            })
    return {"topics": [{"topic": k, "points": v} for k, v in topics.items()]}


def build_note_payload(note: dict) -> dict:
    """精简每条帖子，只喂总结需要的字段，节省 token。"""
    ocr = note.get("image_ocr") or []
    ocr_text = "\n".join([t for t in ocr if t])
    return {
        "note_id": note.get("note_id", ""),
        "url": note.get("url", ""),
        "title": note.get("title", ""),
        "text": note.get("text", ""),
        "image_ocr": ocr_text[:4000],  # 防止单条过长
        "tags": note.get("tags", []),
    }


def render_markdown(summary: dict) -> str:
    quality_label = {"high": "高价值", "medium": "一般", "low": "可跳过"}
    lines = ["# 小红书技术收藏 · 知识点总结", "",
             "> 每个知识点后附原帖链接，可点击溯源。", ""]
    for t in summary.get("topics", []):
        lines.append(f"## {t.get('topic','未分类')}")
        lines.append("")
        for i, p in enumerate(t.get("points", []), 1):
            q = quality_label.get(p.get("quality"), p.get("quality", ""))
            lines.append(f"### {i}. {p.get('point','')} `{q}`")
            if p.get("detail"):
                lines.append(p["detail"])
            srcs = p.get("sources", [])
            if srcs:
                lines.append("")
                lines.append("来源：")
                for s in srcs:
                    title = s.get("title") or s.get("note_id", "原帖")
                    lines.append(f"- [{title}]({s.get('url','')})")
            lines.append("")
    return "\n".join(lines)


def main():
    # 解析 --collection，按当前收藏夹设置隔离目录
    ctx = get_context()
    global NOTES_DIR, EXTRACTED_DIR, OUTPUT_DIR
    NOTES_DIR = ctx.notes_dir
    EXTRACTED_DIR = ctx.extracted_dir
    OUTPUT_DIR = ctx.output_dir
    cfg = ctx.cfg
    print(f"当前收藏夹：[{ctx.id}] {ctx.name}")

    sum_conf = cfg.get("summarization", {})
    if not sum_conf or sum_conf.get("enabled") is False:
        print("config.json 未启用 summarization（或 enabled=false）。")
        print("如需用 API 自动总结：在 config.json 填好 summarization 的 base_url/model/api_key 并设 enabled=true。")
        print("（默认推荐：直接在对话里让 Claude 帮你总结，质量最高、0 成本。）")
        return

    note_files = sorted(NOTES_DIR.glob("*.json"))
    if not note_files:
        print(f"未找到帖子数据（{NOTES_DIR}），请先运行抓取与图片提取。")
        return

    llm = TextLLMProvider(sum_conf)
    batch_size = int(sum_conf.get("batch_size", 8))
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    notes = [json.load(open(nf, encoding="utf-8")) for nf in note_files]

    # --- 增量核心：只对“没有提炼缓存”的新帖调用模型 ---
    new_notes = []
    for n in notes:
        nid = n.get("note_id", "")
        if not (EXTRACTED_DIR / f"{nid}.json").exists():
            new_notes.append(n)

    print(f"总结模型：{llm.model}（每批 {batch_size} 条）")
    print(f"帖子总数 {len(notes)} 条，其中新帖 {len(new_notes)} 条需要分析，"
          f"其余 {len(notes) - len(new_notes)} 条复用已有提炼结果。")

    # ===== 阶段1：逐条提炼（只处理新帖，分批调用以控制单次 token 量）=====
    # build_note_payload 把帖子精简成只含总结需要的字段，省 token
    def try_extract(payloads):
        """对一组帖子调用模型并解析，成功返回 list，失败抛异常。"""
        prompt = PROMPT_EXTRACT.format(
            batch=json.dumps(payloads, ensure_ascii=False, indent=2))
        out = llm.chat(SYSTEM_EXTRACT, prompt)
        arr = parse_json_loose(out)
        if not isinstance(arr, list):
            raise ValueError("返回不是 JSON 数组")
        return arr

    def save_items(arr):
        for item in arr:
            nid = item.get("source_note_id", "")
            if nid:
                with open(EXTRACTED_DIR / f"{nid}.json", "w", encoding="utf-8") as f:
                    json.dump(item, f, ensure_ascii=False, indent=2)

    new_payloads = [build_note_payload(n) for n in new_notes]
    for i in range(0, len(new_payloads), batch_size):
        batch = new_payloads[i:i + batch_size]
        print(f"提炼新帖第 {i//batch_size + 1} 批（{len(batch)} 条）...")
        try:
            save_items(try_extract(batch))
            continue
        except Exception as e:
            print(f"    [整批解析失败] {e} —— 拆成单条逐个重试")
        # 整批失败：拆单条逐个提炼，最大限度抢救（个别帖子内容会让模型输出非法JSON）
        for p in batch:
            try:
                save_items(try_extract([p]))
            except Exception as e2:
                print(f"      [跳过单条 {p.get('note_id','?')}] {e2}")

    # 读取全部提炼结果（新提炼的 + 历史缓存的）一起进入汇总
    extracted_all = []
    for n in notes:
        ef = EXTRACTED_DIR / f"{n.get('note_id','')}.json"
        if ef.exists():
            extracted_all.append(json.load(open(ef, encoding="utf-8")))

    if not extracted_all:
        print("未提炼到任何结果，结束。")
        return

    # ===== 阶段2：把所有提炼结果（新+旧缓存）汇总、按主题归类、合并重复 =====
    # 帖子多时一次性塞给模型容易超时/被截断，这里按上限分块汇总后再拼合，
    # 并对汇总临时调大超时；最终失败则用本地 local_merge 兜底，保证一定有产出。
    print(f"汇总归类去重（共 {len(extracted_all)} 条提炼结果）...")
    summary = None
    old_timeout = llm.timeout
    llm.timeout = max(old_timeout, 300)  # 汇总更耗时，临时调到至少 300s
    try:
        # 分块：每块最多 40 条提炼结果，分别汇总，再合并各块 topics
        CHUNK = 40
        chunk_results = []
        chunks = [extracted_all[i:i + CHUNK] for i in range(0, len(extracted_all), CHUNK)]
        for ci, chunk in enumerate(chunks):
            print(f"  汇总第 {ci + 1}/{len(chunks)} 块（{len(chunk)} 条）...")
            mp = PROMPT_MERGE.format(
                extracted=json.dumps(chunk, ensure_ascii=False, indent=2))
            out = llm.chat(SYSTEM_MERGE, mp)
            r = parse_json_loose(out)
            if isinstance(r, dict) and "topics" in r:
                chunk_results.append(r)
            elif isinstance(r, list):
                chunk_results.append({"topics": r})
        # 合并各块的同名 topic
        merged_topics = {}
        for r in chunk_results:
            for t in r.get("topics", []):
                name = t.get("topic", "未分类")
                merged_topics.setdefault(name, []).extend(t.get("points", []))
        if merged_topics:
            summary = {"topics": [{"topic": k, "points": v}
                                  for k, v in merged_topics.items()]}
    except Exception as e:
        print(f"  [汇总调用失败] {e} —— 改用本地兜底归类（不丢任何知识点）。")
    finally:
        llm.timeout = old_timeout

    # 兜底：模型汇总失败或结果为空时，用本地按 topic_hint 归类，绝不让网页空白
    if not summary or not summary.get("topics"):
        print("  使用本地兜底汇总（按 topic_hint 归类，保留全部知识点）。")
        summary = local_merge(extracted_all)

    # 输出（写入当前收藏夹的 output 目录，并确保有 index.html 网页）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_DIR / "知识点总结.md", "w", encoding="utf-8") as f:
        f.write(render_markdown(summary))
    ctx.ensure_web()  # 从模板复制 index.html 到该收藏夹 output（若没有）

    n_topics = len(summary.get("topics", []))
    n_points = sum(len(t.get("points", [])) for t in summary.get("topics", []))
    print(f"\n完成：{n_topics} 个主题，{n_points} 条知识点。")
    print(f"已写入 {OUTPUT_DIR}/summary.json 和 知识点总结.md")
    print(f"用浏览器打开 {OUTPUT_DIR}/index.html 即可按主题/质量筛选浏览。")

    # 全自动发布：若 config 开启 publish.enabled 且 publish.auto，则自动推送到 GitHub
    pub = cfg.get("publish", {}) or {}
    if pub.get("enabled") and pub.get("auto"):
        print("\n检测到已开启自动发布，正在推送到 GitHub...")
        try:
            from publish import publish as do_publish
            do_publish(cfg)
        except Exception as e:
            print(f"[发布异常] {e}（可稍后手动运行 python scraper/publish.py）")


if __name__ == "__main__":
    main()
