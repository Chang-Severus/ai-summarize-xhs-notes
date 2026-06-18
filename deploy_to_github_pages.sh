#!/usr/bin/env bash
# ============================================================
# 一键把知识点网页发布到 GitHub Pages
# ============================================================
# 用法：
#   1) 在 GitHub 上新建一个空仓库（Public），复制它的地址，例如：
#        https://github.com/你的用户名/xhs-notes.git
#   2) 运行（首次需要传仓库地址）：
#        bash deploy_to_github_pages.sh https://github.com/你的用户名/xhs-notes.git
#   3) 以后更新总结后，直接运行（无需再传地址）：
#        bash deploy_to_github_pages.sh
#   4) 首次推送后，去 GitHub 仓库 Settings -> Pages，
#      Source 选 "Deploy from a branch"，分支选 main、目录选 /docs，保存。
#      稍等 1~2 分钟，页面地址形如：
#        https://你的用户名.github.io/xhs-notes/
#      手机/任意设备打开这个地址即可。
# ============================================================
set -e
cd "$(dirname "$0")"

REPO_URL="$1"

# 1) 准备 docs/ 目录（GitHub Pages 发布源），只放网页所需文件，不含原始数据/Key
echo "==> 同步网页到 docs/ ..."
mkdir -p docs
cp output/index.html docs/index.html
if [ -f output/summary.json ]; then
  cp output/summary.json docs/summary.json
else
  echo "    [提醒] 未找到 output/summary.json，请先生成总结再部署。"
fi

# 2) 初始化 git（若未初始化）
if [ ! -d .git ]; then
  echo "==> 初始化 git 仓库 ..."
  git init
  git branch -M main
fi

# 3) 设置远程地址
if [ -n "$REPO_URL" ]; then
  if git remote | grep -q origin; then
    git remote set-url origin "$REPO_URL"
  else
    git remote add origin "$REPO_URL"
  fi
fi

if ! git remote | grep -q origin; then
  echo "[X] 还没设置 GitHub 仓库地址。首次请这样运行："
  echo "    bash deploy_to_github_pages.sh https://github.com/你的用户名/仓库名.git"
  exit 1
fi

# 4) 提交并推送（.gitignore 已确保 config.json/.auth/data 不会被推上去）
echo "==> 提交并推送到 GitHub ..."
git add .
git commit -m "update: 知识点总结 $(date '+%Y-%m-%d %H:%M')" || echo "    无改动，跳过提交"
git push -u origin main

echo ""
echo "==> 完成！若是首次部署，请到 GitHub 仓库 Settings -> Pages，"
echo "    选择 main 分支的 /docs 目录作为发布源。"
echo "    随后访问： https://<你的用户名>.github.io/<仓库名>/"
