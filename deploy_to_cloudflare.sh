#!/usr/bin/env bash
# ============================================================
# 一键把知识点网页发布到 Cloudflare Pages（免费，可设访问密码）
# ============================================================
# 相比 GitHub Pages 的好处：
#   - 免费额度对静态网页绰绰有余
#   - 可设访问密码（Cloudflare Access，见文末），网页不再人人可见
#   - 不需要公开仓库
#
# 前置：本机已装 Node（已确认 v20）。脚本用 npx 调用 wrangler，无需全局安装。
#
# 用法：
#   首次：
#     bash deploy_to_cloudflare.sh                # 会引导你登录 Cloudflare（浏览器授权）
#   以后更新总结后，直接再跑一次即可：
#     bash deploy_to_cloudflare.sh
#
# 自定义项目名（默认 xhs-notes）：
#     PROJECT_NAME=my-notes bash deploy_to_cloudflare.sh
# ============================================================
set -e
cd "$(dirname "$0")"

PROJECT_NAME="${PROJECT_NAME:-xhs-notes}"

# 1) 准备发布目录 docs/（只含网页，不含 Key/原始数据）
echo "==> 同步网页到 docs/ ..."
mkdir -p docs
cp output/index.html docs/index.html
if [ -f output/summary.json ]; then
  cp output/summary.json docs/summary.json
else
  echo "    [提醒] 未找到 output/summary.json，请先生成总结再部署。"
fi

# 2) 用 wrangler 发布到 Cloudflare Pages
#    首次会自动打开浏览器让你登录授权 Cloudflare 账号（免费注册）。
echo "==> 通过 wrangler 部署到 Cloudflare Pages（项目名：$PROJECT_NAME）..."
echo "    首次运行会弹出浏览器要求登录 Cloudflare，按提示授权即可。"
npx --yes wrangler@latest pages deploy docs --project-name "$PROJECT_NAME"

echo ""
echo "==> 完成！上方输出里会有一个形如 https://$PROJECT_NAME.pages.dev 的网址，"
echo "    手机/任意设备打开它即可。"
echo ""
echo "【可选】给网页加访问密码（只有你能看）："
echo "  1. 登录 https://dash.cloudflare.com -> 进入 Pages 项目"
echo "  2. 左侧 Settings -> 或在 Zero Trust(Access) 里给该 pages.dev 域名添加一个 Access 策略"
echo "  3. 策略选择 'One-time PIN'（邮箱验证码）或指定允许的邮箱，保存"
echo "  之后访问网页会要求邮箱验证，只有你授权的邮箱能进。详见 README。"
