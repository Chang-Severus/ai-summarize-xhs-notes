# -*- coding: utf-8 -*-
"""
自动发布到 GitHub Pages
=====================

把最新的网页（index.html + summary.json）同步到 docs/ 目录，
然后 git add / commit / push 到你的 GitHub 仓库。
GitHub Pages 配置为从 main 分支的 /docs 目录发布后，推送即自动更新线上网页。

用法（通常无需手动调用，summarize.py 总结完会自动调用；也可单独运行）：
  python scraper/publish.py

依赖 config.json 的 publish 配置块：
  {
    "publish": {
      "enabled": true,
      "auto": true,                      // 总结后是否自动推送
      "repo_url": "git@github.com:用户名/仓库名.git",
      "branch": "main"
    }
  }
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"
CONFIG_PATH = ROOT / "config.json"


def run(cmd: list, check=True):
    """运行一条命令，返回 (是否成功, 输出)。"""
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        return False, out
    return True, out


def sync_docs():
    """把 output 里的网页和数据同步到 docs/（GitHub Pages 发布目录）。"""
    DOCS_DIR.mkdir(exist_ok=True)
    shutil.copy(OUTPUT_DIR / "index.html", DOCS_DIR / "index.html")
    if (OUTPUT_DIR / "summary.json").exists():
        shutil.copy(OUTPUT_DIR / "summary.json", DOCS_DIR / "summary.json")
    print(f"已同步网页到 {DOCS_DIR}")


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

    sync_docs()

    # 初始化 git（若未初始化）
    if not (ROOT / ".git").exists():
        run(["git", "init"])
        run(["git", "branch", "-M", branch])

    # 设置/更新远程地址
    ok, _ = run(["git", "remote", "get-url", "origin"], check=False)
    if ok:
        run(["git", "remote", "set-url", "origin", repo_url])
    else:
        run(["git", "remote", "add", "origin", repo_url])

    # 提交并推送
    run(["git", "add", "."])
    msg = f"update: 知识点总结 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ok, out = run(["git", "commit", "-m", msg], check=False)
    if not ok and "nothing to commit" in out:
        print("内容无变化，无需提交。")
    ok, out = run(["git", "push", "-u", "origin", branch], check=False)
    if not ok:
        print("[X] 推送失败：")
        print(out[:500])
        print("\n常见原因：① SSH key 未添加到 GitHub；② 仓库地址错误；"
              "③ 远程已有内容需先 pull。可手动执行 git push 查看详情。")
        return False

    print("✅ 已推送到 GitHub。若已在仓库 Settings->Pages 配置 main/docs，"
          "稍等 1~2 分钟即可在 Pages 网址看到更新。")
    return True


def main():
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8")) if CONFIG_PATH.exists() else {}
    publish(cfg)


if __name__ == "__main__":
    main()
