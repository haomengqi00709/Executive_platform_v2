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

任何涉及邮件的模块，在处理任何一封邮件之前，必须先调用 `src/modules/screener.screen_emails()`。

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

**例外：`expenses` section 不使用 screener。**
Screener 回答"CEO 需要亲自读/处理这封邮件吗？"
Expenses 回答"这个附件是收据吗？"— 只能由 Gemini 看文件内容回答。
`expenses` 直接用 `hasAttachments eq true` 独立 fetch，不调用 `screen_emails()`。

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
