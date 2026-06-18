# -*- coding: utf-8 -*-
"""
列出“尚未被总结过”的新帖
=======================

无论用哪种总结方式（对话里的 Claude / summarize.py），提炼结果都记账在
collections/<id>/data/extracted/{note_id}.json。本脚本对比 notes 与 extracted，
列出还没被分析过的新帖，方便增量处理。

用法：
  python scraper/list_new_notes.py --collection ai           # 打印新帖清单
  python scraper/list_new_notes.py --collection ai --dump    # 额外把新帖导出到该收藏夹的 data/_new_notes.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collection_ctx import get_context  # noqa: E402


def find_new_notes(notes_dir: Path, extracted_dir: Path):
    done = {p.stem for p in extracted_dir.glob("*.json")} if extracted_dir.exists() else set()
    new = []
    for nf in sorted(notes_dir.glob("*.json")):
        if nf.stem not in done:
            new.append(json.load(open(nf, encoding="utf-8")))
    return new, done


def main():
    ctx = get_context()
    print(f"当前收藏夹：[{ctx.id}] {ctx.name}")
    if not ctx.notes_dir.exists():
        print(f"还没有抓取数据（{ctx.notes_dir} 不存在）。")
        return
    new, done = find_new_notes(ctx.notes_dir, ctx.extracted_dir)
    total = len(list(ctx.notes_dir.glob("*.json")))
    print(f"帖子总数 {total} 条，已总结 {len(done)} 条，新帖 {len(new)} 条。")
    if new:
        print("\n待总结的新帖：")
        for n in new:
            print(f"  - {n.get('note_id')}  {n.get('title','')[:40]}")
    else:
        print("没有新帖，全部已总结。")

    if "--dump" in sys.argv and new:
        out = ctx.base_dir / "data" / "_new_notes.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=2)
        print(f"\n已导出新帖内容到 {out}，可整份贴给对话里的 Claude 做总结。")


if __name__ == "__main__":
    main()
