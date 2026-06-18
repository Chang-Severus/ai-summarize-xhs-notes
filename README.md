# 小红书收藏夹 → AI 知识点总结

把你小红书收藏夹里上百条 AI / LLM / Agent 技术帖子，**自动抓取 → 图片提取文字 → 大模型总结**，
最终产出一份**按主题分类、带原帖溯源**的知识点总结，支持 Markdown 文档和可交互网页两种形式。

核心价值：
- 不用一条条刷帖子，直接看提炼好的知识点
- 每个知识点都标了**质量等级**（高价值 / 一般 / 可跳过），一键过滤水帖
- 每个知识点都能**点回原帖**，想细看随时溯源
- 收藏夹加了新帖，**增量更新**只分析新的，不重复花钱

---

## 一、工作原理（整体逻辑）

整个流程分三个阶段，数据一步步流转：

```
阶段一：抓取（脚本，本机跑）
  小红书登录(扫码一次) → 滚动加载收藏夹 → 逐条抓正文+下载图片
  产出：data/notes/*.json（每条帖子一个文件，含原帖链接）
        data/images/*.jpg（帖子图片）
                    │
                    ▼
阶段二：图片提取文字（脚本）
  对每张图片做内容提取（本地OCR 或 多模态大模型）
  产出：把识别文字回填进 data/notes/*.json 的 image_ocr 字段
                    │
                    ▼
阶段三：知识点总结（对话里的 Claude，或 API 脚本）
  读取所有帖子 → 逐条提炼知识点+质量评级 → 跨帖去重、按主题归类
  产出：output/summary.json（结构化，带溯源）
        output/知识点总结.md（可读文档）
                    │
                    ▼
浏览：打开 output/index.html，按主题/质量筛选，点击跳原帖
发布：可选发到 GitHub Pages / Cloudflare Pages，手机也能看
```

**为什么这样设计**：小红书反爬严重，不适合批量调 API；所以抓取用浏览器模拟真人（最稳），
而总结这种需要理解力的活交给大模型。两段解耦，各做擅长的事。

**关键设计 —— 可插拔引擎**：图片提取和知识点总结用的模型都做成了「可切换」，
切换模型基本只改 `config.json`，不用动代码（详见后文「常见需求改动速查」）。

> 抓取部分有几个关键且反直觉的实现细节（点击卡片才能拿到 token、虚拟滚动、登录态判断等），
> 这些是反复踩坑后定下的正确做法，**强烈建议二次开发前先读第九节「抓取实现原理与踩坑记录」**。

---

## 二、文件结构与各自职责

```
.
├── README.md                      # 本说明
├── 方案设计.md                     # 更详细的设计文档（数据流、格式定义）
├── requirements.txt               # Python 依赖（已锁定版本，便于换机复现）
├── config.example.json            # 配置模板
├── config.json                    # 你的实际配置（含Key，已被 .gitignore 忽略）
│
├── scraper/                       # 所有处理脚本
│   ├── fetch_collection.py        # 【阶段一】抓取收藏夹：登录、滚动收集、抓正文、下图
│   ├── ocr_notes.py               # 【阶段二】图片提取文字（按配置选引擎）
│   ├── check_api.py               # 工具：API 连通性自检（填完Key先跑这个验证）
│   ├── summarize.py               # 【阶段三·可选】用API自动总结（支持增量，可自动触发发布）
│   ├── publish.py                 # 把所有收藏夹网页同步到 docs/ 并推送到 GitHub Pages
│   ├── list_new_notes.py          # 工具：列出还没总结过的新帖（增量辅助）
│   ├── collection_ctx.py          # 多收藏夹公共工具：解析 --collection、返回隔离路径
│   └── providers/                 # 可插拔的「模型引擎」抽象层
│       ├── __init__.py            #   引擎工厂：按配置返回对应引擎
│       ├── base.py                #   引擎基类（统一接口）
│       ├── rapidocr_provider.py   #   引擎1：本地免费OCR
│       ├── vlm_provider.py        #   引擎2：多模态大模型读图（兼容OpenAI接口）
│       └── text_llm_provider.py   #   引擎3：文本大模型总结（兼容OpenAI接口）
│
├── prompts/
│   └── summarize_prompt.md        # 总结用的提示词模板与输出规范
│
├── collections/                   # 【多收藏夹隔离】每个收藏夹一个子目录（已被 .gitignore 忽略）
│   └── <id>/                      #   收藏夹 id（如 ai / finance / opensource）
│       ├── data/notes/*.json      #     每条帖子的结构化数据（含原帖链接）
│       ├── data/images/*.jpg      #     下载的帖子图片
│       ├── data/extracted/*.json  #     提炼缓存（增量更新靠它）
│       └── output/                #     summary.json + 知识点总结.md + index.html
│
├── output/index.html              # 网页模板（各收藏夹复用同一份样式）
│
├── docs/                          # GitHub Pages 发布目录（publish.py 自动生成，会上传）
│   ├── index.html                 #   总导航页（列出所有收藏夹）
│   └── <id>/index.html+summary.json  # 各主题子页
│
└── deploy_to_cloudflare.sh        # 备选：一键发布到 Cloudflare Pages（可设访问密码）
```

> 发布到 GitHub Pages 用 `scraper/publish.py`（见第六节）；`deploy_to_cloudflare.sh` 是想要
> 访问密码/私密时的备选。早期的 `deploy_to_github_pages.sh` 已被 `publish.py` 取代。

---

## 三、安装（一次性）

环境用 conda（Python 3.11）。在项目目录下执行：

```bash
conda create -n xhs-summary python=3.11 -y
conda activate xhs-summary
pip install -r requirements.txt
python -m playwright install chromium      # 装抓取用的浏览器内核
```

> 之后每次使用前，先激活环境：`conda activate xhs-summary`
>
> **换电脑**：把整个文件夹拷过去，重复上面四条命令即可（`requirements.txt` 已锁版本）。
> 直接拷贝文件夹会连 `config.json`、登录态、已抓数据一起带走，新机器免重新配置。

---

## 四、配置

复制模板并填写：

```bash
cp config.example.json config.json
```

打开 `config.json`，**你通常只需关心这几处**：

| 配置项 | 含义 | 必填 |
|--------|------|------|
| `collections` | 你的收藏夹列表，每个含 `id`/`name`/`board_url`/`max_notes` | ✅ |
| `image_understanding.api_key` | 调用图片大模型的 API Key（所有收藏夹共用） | 用大模型读图时填 |
| `image_understanding.provider` | 图片引擎：`rapidocr`(免费) 或 `vlm`(大模型) | 默认即可 |

> 当前默认：图片用 `gemini-3-flash`（venus 代理，10 路并发），总结用对话里的 Claude。
> 模型怎么换见第七节。

### 多收藏夹（不同主题互相隔离）

支持多个收藏夹（如 AI、财务、美食、开源项目），**数据和网页各自隔离、互不覆盖**。
在 `config.json` 的 `collections` 数组里，每个收藏夹一项：

```json
"collections": [
  { "id": "ai",         "name": "AI / LLM / Agent 技术", "board_url": "https://www.xiaohongshu.com/board/xxx", "max_notes": 200 },
  { "id": "opensource", "name": "优秀开源项目",          "board_url": "https://www.xiaohongshu.com/board/yyy", "max_notes": 200 }
]
```

- `id`：英文短标识，会用作目录名和网址路径（如 `ai`、`opensource`）。
- 所有脚本用 **`--collection <id>`** 指定操作哪个收藏夹（只有一个时可省略）。
- 数据隔离在 `collections/<id>/`，网页发布在 `docs/<id>/`，共用一份 Key/模型/发布配置。

---

## 五、使用流程

### 首次完整跑一遍

```bash
conda activate xhs-summary

# 1. （建议）先验证图片大模型能用
python scraper/check_api.py

# 2. 抓取某个收藏夹（首次会弹浏览器，扫码登录小红书）
python scraper/fetch_collection.py --collection ai

# 3. 提取图片里的文字（vlm 默认 10 路并发，上百张图几分钟完成）
python scraper/ocr_notes.py --collection ai

# 4. 总结：见下方两种方式
```

> `--collection ai` 指定操作 id 为 `ai` 的收藏夹。如果 `config.json` 里只有一个收藏夹，
> 可以省略 `--collection`，脚本会自动选中那一个。处理别的主题就把 `ai` 换成对应 id。

> 图片提取速度：用大模型(vlm)读图默认 **10 并发**（`config.json` 的 `concurrency`），
> 比串行快 3-4 倍；嫌慢可调大，但过大可能触发 API 限流。rapidocr 本地 OCR 自动串行。

**第 4 步总结，二选一：**

- **方式 A（默认推荐，0 成本、质量最高）**：回到本对话，发一句
  「data/notes 已就绪，开始总结」，我读取数据帮你生成
  `output/summary.json` 和 `output/知识点总结.md`。
- **方式 B（全自动）**：在 `config.json` 把 `summarization.enabled` 设为 `true`、填好 Key，
  然后 `python scraper/summarize.py`。

### 浏览结果

```bash
cd output
python -m http.server 8777
# 浏览器打开 http://localhost:8777/index.html
```

网页支持：按主题筛选、按质量筛选（一键隐藏水帖）、关键词搜索、点击知识点跳转原帖。
也可以直接看 `output/知识点总结.md`。

### 日常：收藏夹加了新帖（增量更新）

直接把流程重跑一遍，**全程只处理新内容**：

```bash
conda activate xhs-summary
python scraper/fetch_collection.py --collection ai   # 已抓过的自动跳过
python scraper/ocr_notes.py --collection ai          # 已处理的自动跳过
python scraper/list_new_notes.py --collection ai     # （可选）看看这次有哪些新帖
```

再总结：
- 方式 A：`python scraper/list_new_notes.py --collection ai --dump` 把新帖导出到
  `collections/ai/data/_new_notes.json`，贴给我，我只总结新帖并与旧的合并。
- 方式 B：`python scraper/summarize.py --collection ai`，自动只分析新帖。

> **增量原理**：每条帖子提炼后会在 `collections/<id>/data/extracted/` 留一份缓存。再次运行时，
> 有缓存的帖子直接复用、不再调模型，只有新帖才会被分析，最后所有知识点统一汇总。

---

## 六、发布到公网（手机/其他设备访问）

### 自动发布到 GitHub Pages（推荐，已和总结流程打通）

**一次性准备**（见下方"首次配置"）后，在 `config.json` 设置：

```json
"publish": {
  "enabled": true,
  "auto": true,
  "repo_url": "git@github.com:你的用户名/仓库名.git",
  "branch": "main"
}
```

之后**用 API 总结（summarize.py）时会自动推送**；也可随时手动发布：

```bash
python scraper/publish.py
```

它会把**所有收藏夹**的网页同步到 `docs/`（每个收藏夹一个子目录），并生成一个总导航页，
自动 commit & push。GitHub Pages 配置为 main 分支 /docs 目录后，推送即自动更新：
- 总导航（列出所有主题）：`https://你的用户名.github.io/仓库名/`
- 某个主题：`https://你的用户名.github.io/仓库名/<id>/`（如 `.../ai/`）

手机/任意设备打开总导航即可在不同主题间切换。

> 只上传 `docs/` 里的网页和总结结果；`config.json`(含Key)、登录态、原始数据
> 已被 `.gitignore` 忽略，**不会上线**。

#### 首次配置（一次性）

1. **生成 SSH key**（若没有）：`ssh-keygen -t ed25519 -C "你的邮箱" -f ~/.ssh/id_ed25519 -N ""`
2. **把公钥加到 GitHub**：`cat ~/.ssh/id_ed25519.pub` 复制内容 →
   GitHub 头像 → Settings → SSH and GPG keys → New SSH key → 粘贴保存
3. **建仓库**：GitHub 右上角 + → New repository → 填名字（如 `xhs-notes`）→
   选 Public → 不勾任何初始化文件 → Create
4. **填 `config.json`** 的 `publish.repo_url` 为 `git@github.com:用户名/仓库名.git`，
   并设 `enabled: true`
5. **首次推送后**，到仓库 Settings → Pages，Source 选 main 分支 + /docs 目录，保存

### 备选：Cloudflare Pages（免费，可设访问密码）

```bash
bash deploy_to_cloudflare.sh    # 首次会引导登录 Cloudflare（免费注册）
```

想加访问密码：登录 Cloudflare 后台，在 Zero Trust(Access) 给该域名加一条
「邮箱验证码(One-time PIN)」策略，只有你授权的邮箱能访问。

---

## 七、常见需求改动速查

| 你想做什么 | 改哪里 |
|-----------|--------|
| **新增一个收藏夹（新主题）** | `config.json` 的 `collections` 加一项（id/name/board_url），再用 `--collection <id>` 跑全流程 |
| **指定操作哪个收藏夹** | 所有脚本加 `--collection <id>`（只有一个收藏夹时可省略） |
| **换图片识别模型**（如 gemini→gpt-4o） | `config.json` → `image_understanding.model` |
| **图片识别换厂商** | 改 `image_understanding` 的 `base_url`+`model`+`api_key`（需兼容 OpenAI 接口） |
| **图片识别改回免费OCR** | `image_understanding.provider` 改成 `rapidocr` |
| **图片提取太慢/想更快** | 调大 `image_understanding.concurrency`（默认10并发；调大更快但可能触发API限流） |
| **开启网页自动发布到GitHub** | `publish.enabled` 设 `true` 并填 `repo_url`；`auto:true` 则总结后自动推送 |
| **换总结模型** | `config.json` → `summarization.model` |
| **开启API自动总结** | `summarization.enabled` 改成 `true` 并填 Key |
| **一次抓更多/更少帖子** | `config.json` → `max_notes` |
| **抓取太快怕风控** | 调大 `scroll_pause_seconds` 和 `note_interval_seconds` |
| **改总结的提炼规则/质量标准** | `prompts/summarize_prompt.md`（方式A）或 `scraper/summarize.py` 里的 `PROMPT_EXTRACT`/`PROMPT_MERGE`（方式B） |
| **改网页样式/筛选逻辑** | `output/index.html` |
| **加一个全新的模型厂商（接口不兼容OpenAI）** | 在 `scraper/providers/` 新增一个 provider 类，主流程不用动 |

> 图片模型(`image_understanding`)和总结模型(`summarization`)是**两套独立配置**，可分别用不同模型。

---

## 八、注意事项

- 本工具仅用于**整理你自己账号有权查看的收藏内容**，脚本已内置延时控制频率，请勿滥用。
- 小红书前端结构可能更新，若某些字段抓为空，脚本会容错跳过；若大面积失效多半是页面选择器要更新，把现象告诉我即可。
- 免费 OCR 对清晰文字效果好，但**花字、复杂背景、手写体容易识别不全**；这类内容建议把图片引擎切成 `vlm`（大模型读图）。
- 用大模型读图时，`model` 必须是**支持视觉的多模态模型**（如 qwen-vl、gemini、gpt-4o），纯文本模型（如 qwen-14b-chat）不能读图。

### 关于系统弹出的权限请求

抓取用的是 Playwright 的 Chromium 浏览器，macOS 可能弹出以下权限，**都可以放心拒绝，不影响功能**：

- **「Chromium」通知**：网页推送通知权限，本工具用不到 → 拒绝
- **App 管理 / 允许更新或删除其他应用**：IDE 层面触发的系统权限，与本项目无关 → 拒绝

> 本项目只需要：浏览器加载网页、读内容、下图、联网。不需要通知、不需要管理其它 App。

---

## 九、抓取实现原理与踩坑记录（二次开发必读）

抓取（`scraper/fetch_collection.py`）是整个项目最易踩坑的部分。下面记录**最终跑通的正确做法**、
**为什么必须这么做**、以及**调试时踩过的坑**，方便以后小红书改版或你二次开发时快速定位。

### 9.1 最终的正确抓取流程

```
1. 打开 xiaohongshu.com → 检测登录态（看“登录”按钮是否存在）→ 未登录则等扫码
2. 打开收藏夹 board 页 → 等 networkidle + sleep → 等到 section.note-item 出现
3. 边滚动边收集所有帖子的 note_id（应对虚拟滚动）→ 得到完整 ID 列表
4. 逐个 ID：滚回顶部 → 找到该卡片 → 点击卡片的 a.cover 封面 → 进入带 token 的详情页
5. 在详情页抓 标题/正文/作者/标签 + 下载图片 → go_back 返回列表 → 抓下一条
```

### 9.2 四个关键坑与正确做法

**坑①：直接用 `/explore/{note_id}` URL 打开详情 → 永远是“当前笔记暂时无法浏览”**

- 现象：收集到帖子链接后，用 `page.goto(explore_url)` 打开，标题全是“当前笔记暂时无法浏览”，正文为空。即使把等待时间拉长也没用。
- 原因：小红书的帖子详情有 **`xsec_token` 校验参数**。收藏夹页面上帖子链接的 href 只是裸的 `/explore/{id}`，**不带 token**；token 是点击卡片时由前端 JS 动态生成的。裸 URL 缺 token 就被风控拦截。
- ✅ 正确做法：**不要新开 URL，而是在收藏夹页内点击帖子卡片的封面（`a.cover`）**进入详情，此时地址栏会变成带 `xsec_token` 的完整 URL（这个带 token 的 URL 同时作为溯源链接存进 `data/notes/*.json` 的 `url` 字段）。

**坑②：卡片里有两个 `<a>`，要点的是可见的那个**

- 卡片 `section.note-item` 内部有两个 a 标签：
  - `<a href="/explore/...">` —— **`style="display:none"` 隐藏的**，用来读 note_id，但点不了（`scroll_into_view_if_needed` 会超时）。
  - `<a class="cover ...">` —— **可见的封面链接，点它才有效**。
- ✅ 正确做法：用隐藏的 a 读 `note_id`，但点击 `a.cover` 进详情。

**坑③：收藏夹是“虚拟滚动”，不能靠“滚到底再抓”**

- 现象：滚动时 `section.note-item` 的数量忽多忽少（30→52→29→10…）抖动，最后稳定在很小的数字，导致只抓到一小部分。
- 原因：收藏夹用**虚拟滚动**——只渲染当前可见的卡片，滚过去的卡片会被从 DOM 移除回收。所以“当前 DOM 里的卡片数”不等于“总帖子数”，靠它判断是否加载完会严重漏抓。
- ✅ 正确做法：**边滚边收集 note_id**（`collect_all_note_ids`），把滚动过程中出现过的 id 全记进一个去重集合，连续多轮无新增才算到底。先拿到完整 ID 列表，再逐个回去点击抓取。

**坑④：登录态检测不能靠字符串匹配，否则会“未登录误判为已登录”**

- 现象：早期用 `"登录" in content and "扫码" in content` 判断，结果未真正扫码就被判为“已登录”，保存了一个无效登录态，导致后续收藏夹页面加载不出内容（页面显示“未连接到服务器”+左下角还有“登录”按钮）。
- ✅ 正确做法：用 **是否存在“登录”按钮**判断（`is_logged_in`：找到可点击的“登录”入口 = 未登录），未登录时持续轮询直到登录按钮消失，再保存登录态到 `.auth/state.json`。

### 9.3 涉及的关键函数（都在 `scraper/fetch_collection.py`）

| 函数 | 职责 |
|------|------|
| `is_logged_in(page)` | 靠“登录”按钮是否存在判断登录态（坑④） |
| `login_if_needed(...)` | 未登录则等扫码，成功后存登录态 |
| `collect_all_note_ids(page, cfg)` | 边滚边收集全部 note_id，应对虚拟滚动（坑③） |
| `find_item_by_note_id(page, nid)` | 滚动定位到指定 note_id 的卡片 section |
| `click_and_fetch_detail(page, item, nid, cfg)` | 点击 `a.cover` 进详情抓取、再 `go_back` 返回（坑①②） |
| `parse_detail_from_page(...)` | 从已打开的详情页抓标题/正文/作者/标签/图片 |

### 9.4 如果以后小红书改版导致抓不到

按这个顺序排查：
1. 跑抓取看卡在哪一步（收集 ID 为 0？还是点击后“无法浏览”？）。
2. **收集 ID 为 0**：卡片容器选择器 `section.note-item` 可能变了 → 用浏览器开发者工具看收藏夹卡片新的 class。
3. **点击后“无法浏览”**：可点击的封面选择器 `a.cover` 可能变了，或 token 机制变了 → 看点击后地址栏 URL 是否含 `xsec_token`。
4. **登录态失效**：删掉 `.auth/state.json` 重新扫码；或 `is_logged_in` 的“登录”按钮选择器需更新。
5. 把具体现象告诉我，我来更新选择器。
