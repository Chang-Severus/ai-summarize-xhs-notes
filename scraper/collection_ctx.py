# -*- coding: utf-8 -*-
"""
收藏夹上下文（多收藏夹隔离的公共工具）
==================================

所有脚本都通过这里来：
  - 解析命令行的 --collection <id> 参数
  - 加载全局 config.json
  - 拿到“当前收藏夹”的配置和它专属的隔离目录

数据隔离结构：
  collections/<id>/
    ├── data/notes/        每条帖子的结构化 JSON
    ├── data/images/       帖子图片
    ├── data/extracted/    提炼缓存（增量用）
    └── output/            summary.json + 知识点总结.md + index.html

用法（在各脚本里）：
  from collection_ctx import get_context
  ctx = get_context()          # 自动读 --collection 参数
  ctx.notes_dir, ctx.images_dir, ctx.output_dir ...
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
COLLECTIONS_DIR = ROOT / "collections"
WEB_TEMPLATE = ROOT / "output" / "index.html"   # 网页模板（各收藏夹复用同一份）


class CollectionContext:
    """封装某个收藏夹的配置 + 隔离路径。"""

    def __init__(self, cfg: dict, coll: dict):
        self.cfg = cfg                  # 全局配置
        self.coll = coll                # 当前收藏夹配置 {id,name,board_url,max_notes}
        self.id = coll["id"]
        self.name = coll.get("name", coll["id"])
        self.board_url = coll.get("board_url") or coll.get("collection_url") or ""

        base = COLLECTIONS_DIR / self.id
        self.base_dir = base
        self.auth_dir = ROOT / ".auth"             # 登录态全局共用（同一个小红书账号）
        self.notes_dir = base / "data" / "notes"
        self.images_dir = base / "data" / "images"
        self.extracted_dir = base / "data" / "extracted"
        self.output_dir = base / "output"

    def ensure_dirs(self):
        for d in (self.auth_dir, self.notes_dir, self.images_dir,
                  self.extracted_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    # 该收藏夹的抓取参数：优先收藏夹自身，缺省回退全局
    def get(self, key, default=None):
        if key in self.coll:
            return self.coll[key]
        return self.cfg.get(key, default)

    def ensure_web(self):
        """确保该收藏夹 output 下有 index.html（从模板复制）。"""
        target = self.output_dir / "index.html"
        if not target.exists() and WEB_TEMPLATE.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(WEB_TEMPLATE, target)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("未找到 config.json，请先 cp config.example.json config.json 并填写。")
        sys.exit(1)
    return json.load(open(CONFIG_PATH, encoding="utf-8"))


def list_collections(cfg: dict) -> list:
    return cfg.get("collections", []) or []


def get_context(default_id: str = None, parse_args: bool = True) -> CollectionContext:
    """
    解析 --collection 参数并返回对应收藏夹上下文。
    若未指定且只有一个收藏夹，则用那一个；多个则报错提示。
    """
    cfg = load_config()
    colls = list_collections(cfg)
    if not colls:
        print("config.json 的 collections 为空，请先添加至少一个收藏夹。")
        sys.exit(1)

    coll_id = default_id
    if parse_args:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--collection", "-c", dest="collection", default=None,
                            help="指定操作哪个收藏夹（config.collections 里的 id）")
        args, _ = parser.parse_known_args()
        if args.collection:
            coll_id = args.collection

    if not coll_id:
        if len(colls) == 1:
            coll_id = colls[0]["id"]
        else:
            ids = ", ".join(c["id"] for c in colls)
            print(f"有多个收藏夹，请用 --collection 指定其中之一：{ids}")
            sys.exit(1)

    match = next((c for c in colls if c["id"] == coll_id), None)
    if not match:
        ids = ", ".join(c["id"] for c in colls)
        print(f"未找到收藏夹 id={coll_id!r}。可用：{ids}")
        sys.exit(1)

    return CollectionContext(cfg, match)
