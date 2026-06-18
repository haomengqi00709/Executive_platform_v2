# CEO Platform v2

## 为什么有 v2

v1 验证了所有核心技术路径（MSAL OAuth、Microsoft Graph API、Gemini AI、Teams 推送），
所有 5 个模块（M01–M05）都跑通了，12 个 dashboard section 都实现了。

**但 v1 有一个根本问题：没有干净的数据流。**

具体表现：
- 每个 section 有多个数据来源，谁先跑就用谁，不一致
- `section_due_today(m02_result=None, wiki_dir=None)` — 这种双路径 fallback 遍布整个 codebase
- multi-user isolation 是后来打补丁加进去的，不是从设计开始就有的
- 每次改一个地方，另一个地方就坏 — 永远在打补丁，永远修不完

**v2 的目标：production-ready，一个干净的、可扩展的版本。**

---

## 产品定位

这个平台的目标是像 Claude Code 帮助工程师一样，帮助高管管理日常工作：

- **日程管理**：今日会议、即将到来的承诺、待办追踪
- **邮件管理**：待回复邮件、草稿生成、跟进追踪、承诺提取
- **会议智能**：录音转录、摘要 / 决策 / 行动项提取
- **商业分析**：客户关系健康度、行业动态、公司情报
- **行政自动化**：发票识别、费用录入、定制任务

---

## 架构原则（v2 的核心，不可违反）

### 原则 1：一个 section，一个数据源，一个状态

每个 section 只从一个地方读数据，写一个 result 文件。
**不存在 fallback，不存在"数据没有就从别处读"。**

```
Graph API / OneDrive / Email
         ↓
    screener.screen_emails()  ← 所有邮件必须先过这里（原则 5）
         ↓
    Sections（各自独立，各有 skill doc）
    每个 section 只读它需要的数据
         ↓
  .data/{user_id}/results/{section_id}.json
         ↓
   FastAPI → Frontend / Teams
```

### 原则 2：每个 section 返回固定结构

```json
{
  "id": "recent_meetings",
  "status": "fresh | stale | not_run | running",
  "last_run": "2026-05-21T07:30:00Z",
  "items": [...],
  "count": 3,
  "empty": false
}
```

前端看到 `not_run` 就显示"尚未运行"，看到 `stale` 就显示数据时间，不用旧数据假装是新数据。

### 原则 3：Multi-user isolation 从第一行代码开始

所有 per-user 数据在 `.data/{user_id}/` 下。
模块函数签名必须接受 `data_dir: Path` 参数，不使用任何全局路径。

### 原则 4：Wiki 只服务会议模块

Wiki = meeting_action_items 的 project knowledge base（会议→项目 mapping + 行动项）。
**不作为任何其他 section 的 fallback 数据源。**

### 原则 5：所有邮件处理必须先经过 screener（不可跳过）

凡是把邮件**呈现给用户**（列表 / 摘要 / digest / recap）的模块，在呈现任何一封邮件之前，必须先调用 `src/modules/screener.screen_emails()`，只展示 `screened_out=False` 的。

```python
from src.modules.screener import screen_emails

messages = screen_emails(
    messages=raw_inbox,
    ai=ai,
    ignored_emails=ignored_emails,   # 从 CRM ignore=True 联系人提取
    business_context=settings.get("business_context", ""),
    display_name=settings.get("display_name", "the executive"),
    progress=progress,
)
visible = [m for m in messages if not m.get("screened_out")]
```

Screener 回答的是"CEO 需要亲自读/处理这封邮件吗？"，所以只有"把 inbound 邮件呈现给用户"的模块才需要它。

**呈现邮件、必须过 screener 的模块：** `reply_needed`、`followup_needed`(呈现部分)、`commitments_extract`、`email_monitor`、`ai_summary`、`yesterday_recap`。

**豁免（不调用 `screen_emails()`）—— 因为它们不呈现 inbound 邮件，而是另一种处理：**
- **`expenses`** — 回答的是"这个附件是收据吗？"（只能 Gemini 看文件内容），直接用 `hasAttachments eq true` 独立 fetch。
- **只读元数据做聚合 / 匹配的模块**：`crm`（把发件人聚合成联系人库）、`relationship_health`（按发件人统计联系频率）、`profile_init`（首次扫件箱建档案）、`followup_needed` 的回复检测（只取 `conversationId` 判断"发出去的有没有被回"，呈现给用户的是你自己发的邮件，不是 inbound）。

---

## 两类任务

### 定时推送（Scheduled）

用户配置「什么时间、跑哪些 section、推送到 Teams」。
适合固定汇报场景：早报、每日邮件摘要、每周关系健康度。

**属于这类的 section：**
- `ai_summary` — 每日早报
- `reply_needed` — 需要我回复的邮件
- `followup_needed` — 对方未回我的邮件
- `commitments_extract` — 承诺提取
- `upcoming_commitments` — 即将到期的承诺
- `relationship_health` — 关键联系人健康度
- `market_intelligence` — 行业动态
- `business_insights` — 商业分析

**待实现：** per-user 定时配置（用户在前端设置「每天 7:00 跑 ai_summary + upcoming_commitments」）。
当前 sections 只能通过 API 或 bot 命令手动触发，没有自动定时运行。

### 事件触发（Event-driven）

有外部事件发生时自动处理，不需要用户手动触发。

**已运行的触发机制（`src/server.py` startup）：**
- Teams bot 轮询 — 每 10 秒，监听用户消息
- Email monitor 轮询 — 每 1 分钟，新邮件到达时推送到 Teams

**触发机制存在但目前需手动触发的：**
- `recent_meetings` / `meeting_action_items` — OneDrive 有新录音上传 → 应自动处理
- `expenses` — 新收据邮件到达 → 应自动识别

**待实现：** 会议录音和收据的自动触发（轮询 OneDrive 或 webhook）。

**their_commitment 自动解除：**
`commitments_state.py` 里的 `mark_done_by_email_id()` 是已有接口，
等 email monitor 集成后，检测到对方已回复/完成时自动调用。

---

## 10 个 Section

| Section ID | 触发类型 | 状态 | 数据来源 |
|---|---|---|---|
| `ai_summary` | Scheduled | ✅ 实现 | calendar + screened inbox + news |
| `reply_needed` | Scheduled | ✅ 实现 | screened inbox |
| `followup_needed` | Scheduled | ✅ 实现 | sent mail + inbox conv_latest |
| `commitments_extract` | Scheduled | ✅ 实现 | screened inbox（增量缓存） |
| `upcoming_commitments` | Scheduled | ✅ 实现 | commitments_extract.json（derived，无 AI） |
| `recent_meetings` | Event-driven | ✅ 实现 | OneDrive .mp4/.vtt → 转录 → AI 提取 |
| `meeting_action_items` | Event-driven | ✅ 实现 | 同上（写 wiki） |
| `expenses` | Event-driven | ✅ 实现 | 见下方三源合一说明 |
| `market_intelligence` | Scheduled | ⬜ 待实现 | Gemini Google Search grounding |
| `relationship_health` | Scheduled | ⬜ 待实现 | email frequency patterns |
| `business_insights` | Scheduled | ⬜ 待实现 | email patterns + external data |

Derived sections（实时计算，无缓存文件，待实现）：
- `due_today` — 从 `commitments_extract.json` 过滤 due_date == today
- `yesterday_recap` — 从 `reply_needed.json` 过滤昨天收到的邮件
- `meetings_today` — Graph API live call，无缓存

### Expenses 的处理逻辑（多源 + 多文档类型）

收据/发票/合同统一走 expenses section，由 Gemini 分类成三类文档：
- **receipt** → 已付款的开销 → 提取 vendor/amount/GST → **写入 `expenses_master.xlsx`** 用于报销
- **invoice** → 待付款账单 → 提取 vendor/amount/due_date → **不进 Excel**，前端展示
- **contract** → 法律协议 → 提取 counterparty/subject → **不进 Excel**，前端展示

所有类型都进 `results/expenses.json` 的 `items` 列表，每条带 `document_type` 字段。
**`invoices_contracts` 不是独立 section** — 已合并到 expenses。

**来源 1：Email**（已实现）
```
扫邮件附件（PDF / 图片）— hasAttachments eq true
    → 不经过 screener（screener 无法判断附件类型）
    → Gemini vision 分类 + 提取（document_type + 字段）
    → dedup by message_id + attachment_name + sha256 hash
    → receipt 进 Excel，invoice/contract 只进 results JSON
```

**来源 2：Teams 图片**（待实现）
```
用户在 Teams 对话里发给 Audrey 一张收据图片
    → bot 检测到图片附件 → Gemini vision 提取
    → 追加 expenses_master.xlsx
```

**来源 3：OneDrive 固定文件夹**（待实现）
```
用户把收据图片/PDF 保存到 OneDrive 的指定文件夹（路径在 settings 里配置）
    → 轮询检测新文件（与 email monitor 同样的轮询机制）
    → Gemini vision 提取 → 追加 expenses_master.xlsx
```

三个来源的 dedup key 统一：`source_type + source_id + attachment_name`，防止同一张收据被重复录入。

---

### Section 代码组织

每个 section 一个文件：`src/sections/{section_id}.py`

Skill 文件：`src/skills/{section_id}/skill.md` — AI 提示词
用户指令：`data_dir/instructions/{section_id}.md` — 用户通过 API 或 bot 自定义 AI 行为

共享工具：
- `src/modules/screener.py` — 邮件筛选
- `src/modules/crm.py` — CRM 读写
- `src/modules/commitments_cache.py` — commitments 增量缓存（30天）
- `src/modules/commitments_state.py` — commitment 生命周期（done/snooze/asked）
- `src/modules/validator.py` — 通用二次审核

---

## 代码知识库（`kb/`）与 feedback-board

`kb/` 是一个 LLM 维护的代码知识库（markdown），给内部团队的 feedback-board 服务做 AI 问答用。
约定见 `kb/KB_GUIDE.md`。**它不是 meeting `wiki/`，不放 per-user 数据，是 repo-wide 进 git 的。**

**维护钩子（改完代码必须做）：**
改完某 section 的行为 / prompt 后 → 更新它对应的 `kb/capabilities/*.md`（bump frontmatter 的
`derived_from_commit` + `last_synced`）+ 给 `kb/log.md` append 一行；**push 前跑 `python kb/lint.py`，
必须 exit clean**。`lint.py` 用 git 比对每页 `describes_files` 自 `derived_from_commit` 后有没有变，
检测过期。改了哪些文件、影响哪些页：`python kb/lint.py --files <changed files>`。

易变事实**不冻进 KB**：某 section 当前 prompt 的真相源是 `src/skills/{id}/skill.md`（feedback-board
实时读原文）；已知问题的真相源是 feedback-board 的 `requests.json`。

`feedback-board/` 是独立 Railway service（克隆 `ops-dashboard/`），对主程序**零侵入**：不 import 主
`src/`、不写 `.data/`，构建时只 COPY 一份 `kb/` + `src/skills/` 只读副本。详见 `feedback-board/README.md`。

---

## 前端待完成

**定时任务配置页面（尚未实现）：**
- 用户选择「哪些 section 定时跑、几点推送」
- 每个 scheduled section 可配置推送频率（每天/每周）和推送时间
- 存储在 `.data/{user_id}/schedules.json`

**已有前端页面：**
- Dashboard（各 section 结果展示）
- Settings（CRM ignore、bot 配置、display_name 等）
- CRM / Context / AI Chat

---

## Scheduler 架构（`src/server.py` startup）

```
APScheduler BackgroundScheduler（全局单例）
├── Teams bot poll        — interval 10s   — 所有用户
├── Email monitor poll    — interval 1min  — 所有用户
├── CRM daily refresh     — cron 06:00 UTC — 所有用户
├── Projects daily refresh— cron 06:30 UTC — 所有用户
└── [待实现] Per-user section jobs
      从 .data/{user_id}/schedules.json 加载
      用户可在前端配置：section_id + cron 表达式
```

---

## 技术栈

Python 3.13 · FastAPI · MSAL OAuth · Microsoft Graph API ·
Google Gemini 2.5 Flash · Teams Adaptive Cards · APScheduler ·
React + TypeScript + Vite + Tailwind CSS

---

## v1 已验证的关键结论（不要重新踩坑）

- Calendar 必须用 `get_calendar_view()`，不能用 `get_events(filter=...)`
- MSAL authority 必须用 `/common`（多租户）
- Teams Adaptive Card 不能用 `{"type":"Separator"}`，用下一个元素的 `"separator":true`
- `Action.ToggleVisibility` 在 Teams webhook 里不支持
- Draft 邮件只存 Drafts folder，绝不自动发送
- Railway 的 `.data/` 目录需要挂载 volume 才能持久化

---

## 工作原则

**每次修改前，必须用中文向用户说明：**
1. 准备改什么
2. 为什么这样改（不是别的方案）
3. 会影响哪些现有文件

用户确认后才动代码。

**代码标准：**
- 每个函数、模块只做一件事
- 没有 fallback 到另一个数据源（数据不存在就返回 not_run）
- 没有双路径逻辑（`if result is not None ... else wiki`）
- 新功能必须从第一行开始考虑 `data_dir`（per user_id）
- 不写注释解释"做了什么"，只在 WHY 不明显时写

**AI 边界（核心原则）：**

AI 负责**判断、分析、生成自然语言**；不负责**计算事实**。
凡是能从 Graph API / 数据库元数据 / 系统时钟里直接拿到的东西，**代码自己算**，
不传给 AI 让它"输出"。

- ✅ 让 AI 判断"这封邮件值不值得回复"、"这是不是个真承诺"、"用什么语气写"
- ✅ 让 AI 提取"承诺的内容是什么"、"用户意图是什么"
- ❌ 不要让 AI 算"等了几天"、"几封邮件"、"最近一次联系是什么时候"
  — 这些 `sentDateTime` / `len(items)` / `last_contact` 都是确定的，AI 编出来会比真值差
- ❌ skill 的 output 模板里**不要写具体值**（"days_waiting": 5、"Acme Q3 Deal"），
  AI 会直接 copy。用占位符：`<integer matching N>`、`<sender real first name>`
- ❌ Python 里**绝不**写 `ai_response.get("X") or fallback()` —
  AI 真返回 0 会被 falsy 吞掉走 fallback，hallucinate 一个非零数字反而压过真值

不遵守这些会发生：用户看到"今天发的邮件等了 4 天"、"Acme Corp / John Doe"
之类的明显假数据。已踩过的坑见 `docs/auth-health-review-findings.md` 和这次的
`followup_needed` days_waiting bug。

---

## 部署：Railway + Azure 双轨 (同一代码，不同 infra)

### 核心模型

**ONE 代码库（main 分支），TWO 部署目标，差异在 deploy 配置而非代码。**

```
GitHub main 分支
    │
    ├──► Railway (内部测试 / 自动 rebuild on push)
    └──► Azure App Service (客户演示 / 手动 az acr build)
```

代码改动**默认推 main**，两边都收益。

### 两个平台的差异（**只在配置层，不在代码层**）

| 项 | Railway | Azure |
|---|---|---|
| `DATA_DIR` env | 默认 `.data` (相对路径) | `/mnt/data` |
| `.data/` 持久化 | Railway volume mount | Azure Files (`ceodata` mount) |
| Container image 来源 | Railway 自建 | `ceoplatformv2acr.azurecr.io/ceo-platform:vN` |
| 启动端口 | `$PORT` (Railway 注入) | `WEBSITES_PORT=8080` (Azure 注入) |
| OAuth App Registration | 共享同一个 (`PROD_CLIENT_ID=6e538eee-...`)，redirect URI 列表两个 URL 都在 |

代码用 env vars 适配两边——`src/auth.py:27` `DATA_DIR = os.getenv("DATA_DIR", ...)` 是范式。

### 什么时候用 branch（罕见）

**默认不用 branch**。只在**真正实验性、可能搞坏另一边**时用 feature branch：

| 场景 | 用 branch? |
|---|---|
| 加 ffmpeg / 改 Dockerfile / 加前端 page | ❌ 直接进 main |
| 给 Azure 加 Application Insights / Key Vault SDK | ❌ Railway 也能跑（向后兼容） |
| 实验 Azure OpenAI 替代 Gemini（大改 ai.py） | ✅ feature branch，验证后 merge |
| 重写 m03 用别的库 | ✅ feature branch |
| Per-customer 定制（不该有，用 env / settings 走） | ❌ 一定走配置 |

**原则**：除非改动**只对一个平台有意义**或**可能炸另一个**，否则进 main。

### 想控制 Railway rebuild 时机

不用 branch。用：
1. Railway dashboard → 关 auto-deploy → 手动 trigger
2. Push 前本地 Docker build 测试
3. Push 后立刻盯 Railway 日志，有问题 rollback

### Azure 部署的手动操作

每次想让 Azure 拉新代码：
```bash
# 在 main 分支
az acr build --registry ceoplatformv2acr --image ceo-platform:vN \
  --image ceo-platform:latest --platform linux/amd64 .
az webapp config container set --name ceo-platform-v2 --resource-group ceo-platform \
  --docker-custom-image-name ceoplatformv2acr.azurecr.io/ceo-platform:vN
az webapp restart --name ceo-platform-v2 --resource-group ceo-platform
```

**每次 build 用新 tag (`v2`, `v3`, ...)** ——`v1` 等老 tag 保留作回滚目标。

### Azure-specific 资源（不在代码里）

- ACR: `ceoplatformv2acr` (image registry)
- Storage Account: `ceoplatformv2data` (StorageV2 + GPv2, file share `data`)
  - 老的 `ceoplatformv2storage` 是 FileStorage kind，App Service 不能挂，保留待删
- App Service: `ceo-platform-v2` (B1 Linux Container, Always On)
- URL: `https://ceo-platform-v2-g7fuddhnhreqdeax.canadacentral-01.azurewebsites.net`

### 常见踩坑（不要重复）

- **Azure mount path 不能含 `.`** —— 挂 `/mnt/data` 不挂 `/app/.data`，配合 `DATA_DIR=/mnt/data` env
- **Storage account kind 必须 `StorageV2`** —— `FileStorage` 的 ProvisionedV2 SMB App Service 不支持
- **Mac M 系列 build 必须 `--platform linux/amd64`** —— 用 `az acr build` 自动正确；本地 Docker 必须显式加
- **不要用 sitecontainers API** —— 跟老版 `linuxFxVersion=DOCKER\|...` 冲突；用老版 `DOCKER_CUSTOM_IMAGE_NAME` + `az webapp config storage-account add`
