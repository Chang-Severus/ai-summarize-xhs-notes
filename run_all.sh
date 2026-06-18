#!/usr/bin/env bash
# =============================================================
# 无人值守编排脚本：依次跑两个收藏夹的完整流程
#   每个收藏夹： 抓取 -> 图片提取 -> 总结(内部自动发布) -> 兜底再发布一次
# 先跑 AI 收藏夹（全量 184），跑完总结+发布；再跑 opensource 收藏夹。
# 用 tmux 挂后台运行；日志落盘 logs/run_all_*.log。
#
# 注意：抓取用真实浏览器(headless=false)，浏览器窗口会在桌面弹出，属正常现象。
# =============================================================
set -uo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
mkdir -p logs
TS="$(date +%Y%m%d_%H%M%S)"
LOG="logs/run_all_${TS}.log"

# 激活 conda 环境
source ~/miniconda3/etc/profile.d/conda.sh
conda activate xhs-summary

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# 跑单个收藏夹的完整流程；任一步失败仅记录，不中断后续收藏夹
run_collection() {
  local cid="$1"
  log "==================== 开始收藏夹 [$cid] ===================="

  log "[$cid] 步骤1/4 抓取帖子 ..."
  if python -u scraper/fetch_collection.py --collection "$cid" >>"$LOG" 2>&1; then
    log "[$cid] 抓取完成"
  else
    log "[$cid] [警告] 抓取脚本返回非0，继续后续步骤（可能部分已抓到）"
  fi

  log "[$cid] 步骤2/4 图片提取(VLM gemini-3-flash, 并发10) ..."
  if python -u scraper/ocr_notes.py --collection "$cid" >>"$LOG" 2>&1; then
    log "[$cid] 图片提取完成"
  else
    log "[$cid] [警告] 图片提取返回非0，继续"
  fi

  log "[$cid] 步骤3/4 知识点总结(claude-opus-4-6)，内部会自动发布 ..."
  if python -u scraper/summarize.py --collection "$cid" >>"$LOG" 2>&1; then
    log "[$cid] 总结完成"
  else
    log "[$cid] [警告] 总结返回非0"
  fi

  log "[$cid] 步骤4/4 兜底再发布一次（确保 GitHub 已更新） ..."
  if python -u scraper/publish.py >>"$LOG" 2>&1; then
    log "[$cid] 发布完成"
  else
    log "[$cid] [警告] 发布返回非0"
  fi

  log "==================== 收藏夹 [$cid] 结束 ===================="
}

log "########## 任务开始 ##########"
log "日志文件：$LOG"

run_collection "ai"
run_collection "opensource"

log "########## 全部任务完成 ##########"
log "GitHub Pages 总导航： https://chang-severus.github.io/ai-summarize-xhs-notes/"
