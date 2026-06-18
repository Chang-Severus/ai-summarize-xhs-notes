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
│   ├── publish.py                 # 把网页自动同步到 docs/ 并推送到 GitHub Pages
│   ├── list_new_notes.py          # 工具：列出还没总结过的新帖（增量辅助）
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
├── data/                          # 运行产生的数据（已被 .gitignore 忽略）
│   ├── notes/*.json               #   每条帖子的结构化数据（含原帖链接）
│   ├── images/*.jpg               #   下载的帖子图片
│   └── extracted/*.json           #   每条帖子的「提炼缓存」，增量更新靠它
│
├── output/                        # 最终成果
│   ├── summary.json               #   结构化总结（带溯源），网页的数据源
│   ├── 知识点总结.md               #   人类可读的总结文档
│   └── index.html                 #   可交互网页（筛选/搜索/跳原帖）
│
├── deploy_to_github_pages.sh      # 一键发布到 GitHub Pages
└── deploy_to_cloudflare.sh        # 一键发布到 Cloudflare Pages（可设访问密码）
```

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
| `collection_url` | 小红书网页版收藏夹的地址栏链接 | ✅ |
| `image_understanding.api_key` | 调用图片大模型的 API Key | 用大模型读图时填 |
| `image_understanding.provider` | 图片引擎：`rapidocr`(免费) 或 `vlm`(大模型) | 默认即可 |
| `max_notes` | 一次最多抓多少条（上百条建议分批） | 选填 |

> 当前默认：图片用 `gemini-2.5-flash`（venus 代理），总结用对话里的 Claude。
> 模型怎么换见第七节。

---

## 五、使用流程

### 首次完整跑一遍

```bash
conda activate xhs-summary

# 1. （建议）先验证图片大模型能用
python scraper/check_api.py

# 2. 抓取收藏夹（首次会弹浏览器，扫码登录小红书）
python scraper/fetch_collection.py

# 3. 提取图片里的文字（vlm 默认 10 路并发，上百张图几分钟完成）
python scraper/ocr_notes.py

# 4. 总结：见下方两种方式
```

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
python scraper/fetch_collection.py   # 已抓过的自动跳过
python scraper/ocr_notes.py          # 已处理的自动跳过
python scraper/list_new_notes.py     # （可选）看看这次有哪些新帖
```

再总结：
- 方式 A：`python scraper/list_new_notes.py --dump` 把新帖导出到 `data/_new_notes.json`，贴给我，我只总结新帖并与旧的合并。
- 方式 B：`python scraper/summarize.py`，自动只分析新帖。

> **增量原理**：每条帖子提炼后会在 `data/extracted/` 留一份缓存。再次运行时，
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

它会把 `output/index.html` + `summary.json` 同步到 `docs/`，自动 commit & push。
GitHub Pages 配置为 main 分支 /docs 目录后，推送即自动更新线上网页，
访问 `https://你的用户名.github.io/仓库名/`，手机/任意设备可看。

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
