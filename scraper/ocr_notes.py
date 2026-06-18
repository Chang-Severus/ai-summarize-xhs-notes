# -*- coding: utf-8 -*-
"""
图片内容提取脚本（可切换：本地免费OCR / 多模态大模型）
===================================================

对 data/notes/*.json 里每条帖子的图片做内容提取，把结果回填到 image_ocr 字段，
让图片型干货也能进入后续的大模型总结。

提取引擎由 config.json 的 image_understanding.provider 决定：
  - "rapidocr"（默认）：本地、免费、离线。适合白底黑字截图；花字/复杂排版效果一般。
  - "vlm"            ：多模态大模型视觉理解。效果好，按量付费，兼容 OpenAI 接口，可切换厂商。

用法：
  python scraper/ocr_notes.py
  # 想换引擎，改 config.json 的 image_understanding.provider 即可，无需改代码。
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "data" / "notes"
CONFIG_PATH = ROOT / "config.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import get_provider  # noqa: E402


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # 没有 config 也能跑：默认用免费 OCR
    return {"image_understanding": {"provider": "rapidocr"}}


def main():
    note_files = sorted(NOTES_DIR.glob("*.json"))
    if not note_files:
        print("未找到帖子数据，请先运行 scraper/fetch_collection.py")
        return

    cfg = load_config()
    # 根据配置拿到图片引擎（rapidocr 本地OCR 或 vlm 大模型），上层逻辑通用
    provider_name = (cfg.get("image_understanding", {}) or {}).get("provider", "rapidocr")
    print(f"图片提取引擎：{provider_name}")
    print("初始化引擎中（rapidocr 首次会下载模型；vlm 会校验配置）...")
    try:
        provider = get_provider(cfg)
    except Exception as e:
        print(f"初始化失败：{e}")
        return

    # 并发数：vlm（调 API）默认并发 10 加速；rapidocr 是本地 CPU 模型，并发无益故强制为 1
    iu = cfg.get("image_understanding", {}) or {}
    concurrency = int(iu.get("concurrency", 10))
    if provider_name == "rapidocr":
        concurrency = 1

    total = len(note_files)

    # 1) 先扫描所有帖子，收集“待处理的图片任务”，并跳过已处理的帖子
    #    task = (note_file, 帖子内第几张图 idx, 图片绝对路径)
    notes_cache = {}        # note_file -> note dict
    note_text_slots = {}    # note_file -> [按图片顺序占位的文字列表]
    tasks = []
    for nf in note_files:
        note = json.load(open(nf, encoding="utf-8"))
        notes_cache[nf] = note
        images = note.get("images", [])

        # 增量：已提取过则跳过
        if note.get("image_ocr") and len(note["image_ocr"]) >= len(images) > 0:
            note_text_slots[nf] = None  # 标记跳过
            continue
        if not images:
            note["image_ocr"] = []
            note_text_slots[nf] = None
            continue

        slots = [""] * len(images)
        note_text_slots[nf] = slots
        for idx, img_rel in enumerate(images):
            img_path = ROOT / img_rel
            if img_path.exists():
                tasks.append((nf, idx, img_path))

    todo_notes = sum(1 for v in note_text_slots.values() if v is not None)
    print(f"共 {total} 条帖子，待处理 {todo_notes} 条、{len(tasks)} 张图片，"
          f"并发数 {concurrency}。")

    # 2) 用线程池并发提取每张图片（IO 密集型，线程池即可显著加速）
    done = {"n": 0}

    def work(task):
        nf, idx, img_path = task
        text = provider.extract(img_path)
        note_text_slots[nf][idx] = text
        done["n"] += 1
        if done["n"] % 10 == 0 or done["n"] == len(tasks):
            print(f"  已完成 {done['n']}/{len(tasks)} 张图片")
        return True

    if tasks:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, tasks))

    # 3) 把每条帖子的图片文字按顺序回填并写盘
    for nf, slots in note_text_slots.items():
        if slots is None:
            continue
        note = notes_cache[nf]
        note["image_ocr"] = slots
        with open(nf, "w", encoding="utf-8") as f:
            json.dump(note, f, ensure_ascii=False, indent=2)

    print(f"\n处理完成，已回填到 {NOTES_DIR} 的各 JSON 文件。")
    print("接下来：把 data/notes/ 的内容交给对话里的大模型做知识点总结（见 README）。")


if __name__ == "__main__":
    main()
