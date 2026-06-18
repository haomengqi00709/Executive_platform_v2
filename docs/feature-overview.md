---
title: "Executive Assistant"
subtitle: "Feature Overview"
date: "Version 1.0"
---

> 本文档概述 Executive Assistant 当前的产品功能，按用户使用模式分为三大类。文档目的是让读者对平台的能力边界形成完整、客观的认知。

---

# 1. 产品概述

Executive Assistant 是一款面向高管的 AI 助理。它接入用户的 Microsoft 365 环境（Outlook、Calendar、OneDrive、Teams），围绕高管日常工作场景提供三类功能：

- **智能内容推送**：AI 主动分析数据、推送每日洞察，用户无需手动触发
- **结构化数据管理**：用户在平台内维护自己的业务数据（联系人、项目、公司）
- **按需工作流**：用户主动触发特定的 AI 任务

输出渠道有两个：Web Dashboard 与 Microsoft Teams（通过专属的 AI 助理 bot 推送）。

---

# 2. 功能分类

平台的功能按用户交互模式分为三大类：

| 类别 | 描述 | 用户交互模式 |
|---|---|---|
| **类 1 — Intelligence Delivery** | AI 主动计算并推送洞察 | 用户"打开就看到 AI 准备好的内容" |
| **类 2 — Data Management** | 用户维护结构化的业务记录 | 用户"管理自己的业务数据" |
| **类 3 — Workflow Tools** | 用户触发特定的 AI 任务 | 用户"让 AI 帮我完成一件具体的事" |

---

# 3. 类 1 — Intelligence Delivery（智能内容推送）

AI 主动分析数据并交付结果。该类下包含 18 个智能 section、推送编排机制、以及两个输出渠道。

## 3.1 智能 Section（18 个，按 7 个 category 组织）

| Category | Section | 内容 |
|---|---|---|
| **Briefing（早报）** | AI Morning Summary | 每日早间总结：当日日程、值得回复的邮件、关键关系、行业相关动态 |
| **Email（邮件）** | Reply Needed | 收件箱中待回复的邮件，按优先级排序，附原因说明和建议开场白 |
| | Followup Needed | 已发出但未获回复的邮件，标注等待天数和建议跟进语气 |
| | Commitments Extract | 从邮件中提取承诺事项：谁承诺了什么、何时完成 |
| | Upcoming Commitments | 未来 7 天内到期的承诺 |
| | Due Today | 当日到期的承诺与待办 |
| | Yesterday Recap | 前一日的回顾：收发邮件、会议、新增承诺 |
| **Meetings（会议）** | Meetings Today | 当日日程，含与会人和会议链接 |
| | Recent Meetings | 近期会议的总结、决策、行动项（基于录音转录） |
| | Meeting Action Items | 跨会议汇总的所有待办事项 |
| **Projects（项目）** | Projects Needing Attention | 状态异常的项目（停滞、需关注、新阶段） |
| | Project Status | 所有项目的全景视图（状态、势头、最近活动、下一步） |
| **Intelligence（情报）** | Relationship Health | 关键联系人的关系健康度：联系频率、降温信号、建议动作 |
| | Market Intelligence | 行业动态（监管、融资、并购、技术变化），基于 Google Search 检索 |
| | Company Intelligence | 用户标记监控的特定公司的新闻动态 |
| **Insights（洞察）** | Business Insights | 每周一次的商业总结：趋势、统计、要点 |
| **Documents（文档）** | Expenses | 已识别的收据、发票、合同 |

## 3.2 推送编排

用户可配置 AI 主动推送的方式：

| Feature | 说明 |
|---|---|
| **Scheduled Briefings** | 用户配置 cron 时间表、section 组合与推送渠道。每位用户可创建多份独立的 briefing（例如"工作日早 7 点推 AI Summary + Due Today + Meetings Today"）。 |
| **Email Monitor** | 新邮件到达时实时推送至 Teams，不需等待定时早报。支持配置工作时间窗口、digest 间隔、是否启用"重要邮件优先"。 |
| **Meeting Autoresponder** | 新会议录音上传至 OneDrive 时，自动触发会议总结流程、推送至 Teams、并在 Outlook Drafts 自动起草 follow-up 邮件。 |
| **Per-section Instructions** | 每个 section 支持用户编写自定义 instruction（自由文本），用于引导 AI 行为（例如在 Reply Needed 中说明"不需要看营销类邮件"）。 |

## 3.3 输出渠道

| 内容 | 输出位置 |
|---|---|
| 全部 18 个 section | Web Dashboard（详情页支持完整列表与行内 action） |
| Briefing 中选定的 section | Microsoft Teams（按 schedule 推送） |
| Email Monitor 触发的邮件 | Microsoft Teams（实时推送） |
| 会议总结 | Microsoft Teams 推送 + Outlook 草稿 |

---

# 4. 类 2 — Data Management（数据管理）

用户主动维护的结构化业务对象数据库。所有数据管理 feature 共用统一模式：列表视图 + 搜索 / 筛选 / 排序 + 行内编辑 + 批量操作 + 导入 / 导出。

| Feature | 数据类型 | 数据来源 | 用户可执行操作 |
|---|---|---|---|
| **CRM**（联系人） | 个人（含邮箱、所属公司、角色、状态、优先级、关系总结） | 自动扫描 6 个月邮件构建；支持手动新增 / 批量导入 / 文件上传（CSV、Excel、PDF、Word） | 编辑任意字段、合并重复条目、归档、忽略、Excel 导出 |
| **Projects**（项目） | 项目（含状态、势头、参与人、下一步动作） | AI 从邮件会话推断；支持手动新增 / 编辑 | 编辑、合并、归档、Excel 导出 |
| **Companies**（公司） | 组织（按 email domain 识别） | 自动从 CRM 与 Projects 派生；支持手动新增（监控目标公司） | 编辑名称、aliases、"Company Intelligence 监控"开关、删除（仅手动条目）、Excel 导出 |
| **Cleanup**（数据整理） | 跨上述三类数据的 AI 整理建议 | AI 每周自动扫描，按置信度（high / medium / low）分组，标记失效条目 | 批准或拒绝批量操作 |

### 共用组件

- **MergePicker**：通过搜索定位重复记录并执行合并，字段自动合并
- **BulkUploadModal**：支持拖拽上传 CSV / Excel / PDF / Word，AI 自动提取记录，用户预览后选择导入条目

---

# 5. 类 3 — Workflow Tools（工作流工具）

用户主动触发的 AI 任务。与类 2 的核心区别在于：类 3 不是维护持续性数据，而是触发一次性的工作。

| Feature | 任务 | 触发方式 |
|---|---|---|
| **Outreach** | 批量为一组联系人生成个性化外联邮件草稿 | 两种触发路径：(1) 在 Teams 中向 AI 助理发起请求（例如"为标记 Berlin Summit 的联系人起草外联邮件"）；(2) 上传至 OneDrive 的指定文件夹（名片照片 / CSV / Excel / PDF），AI 提取联系人后批量起草。所有草稿保存于 Outlook Drafts，由用户审阅后发送。 |
| **Expenses** | 将收据、发票、合同自动转换为可报销的 Excel 账目 | 两条触发路径：(1) 自动——邮件附件或 OneDrive 新文件被 AI 识别后，自动提取 vendor、amount、日期，写入 expenses_master.xlsx；(2) 手动——通过前端添加、编辑、删除条目，导出 Excel。 |
| **Draft Composer** | 单封邮件的 AI 起草与多轮 refine | 嵌入于 Reply Needed、Followup Needed、CRM 等多个位置。用户点击"Draft reply"，AI 生成初稿；用户可追加要求（如"改得更正式"、"加上致谢"）逐步迭代；满意后保存至 Outlook Drafts。 |

---

# 6. 配套基础设施

平台还包含支撑上述功能的基础设施。这些不是独立 feature，但属于产品完整体验的一部分：

| 模块 | 作用 |
|---|---|
| **Microsoft OAuth 登录** | 用户通过 M365 账号登录平台；所有数据访问基于该 OAuth token |
| **Onboarding Wizard**（3 步引导） | 首次登录引导：粘贴公司网站 → 确认 AI 提取的公司信息 → 连接 Teams 助理 bot。完成后后台自动执行初始化流程（构建 CRM / Projects / Companies、起草 Profile 文档）。 |
| **Profile & Context** | 三份 AI 上下文文档：Personal Profile（用户身份）、Business Profile（公司定位）、Market Segments（关注的市场）。所有 section 在运行时读取这些上下文 |
| **Activity Drawer** | 任务进度面板，实时显示所有后台任务的执行日志 |
| **In-app Chat** | 嵌入式聊天框，用户可在 Web 端直接与 AI 助理对话（除 Teams 之外的额外入口） |
| **Settings 面板** | 系统配置：display_name、company_name、bot 连接管理、Teams webhook URL、自动清理偏好 |

---

# 7. 功能查询索引

| 用户需求 | 对应章节 |
|---|---|
| 平台每天主动告诉我什么？ | §3 类 1（18 个 section + 推送编排） |
| 我能管理客户名单 / 项目吗？ | §4 类 2（CRM、Projects、Companies） |
| 我能批量发外联邮件吗？ | §5 类 3（Outreach） |
| 报销流程如何处理？ | §5 类 3（Expenses） |
| AI 如何了解我所在的业务？ | §6 基础设施（Profile & Context） |
| 客户第一次使用如何上手？ | §6 基础设施（Onboarding Wizard） |
| 结果在哪里查看？ | §3.3 输出渠道 |
