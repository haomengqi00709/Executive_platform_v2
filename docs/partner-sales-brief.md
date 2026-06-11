# Partner Sales Brief — CEO Platform

> 给销售合伙人看的产品 capability statement。
> 说清楚：我们能承诺什么、有哪几种 deployment、距离每种成熟交付有多远。
> 这不是 sales material，是给 partner 的"内部参考"——让他不会承诺出我们做不到的东西。

---

## 1. 产品现状

**CEO Platform** — 给 CEO 的 AI 助理。处理邮件、日历、会议、关系、费用，推送到 Teams。

**生产验证**：IPS Consultancy（Daniel Brown）单客户 BYOC 部署，每天使用中。

### 功能成熟度

| 模块 | 状态 | partner 可承诺给客户 |
|---|---|---|
| M01 早报 | ✅ 生产 | 每日早晨自动推送 |
| M02 邮件分类 + 草稿 | ✅ 生产 | 30 天扫描 + AI 分类 + 自动起草 |
| M03 会议转录 | ✅ 生产 | OneDrive 录音 → 摘要 + action items |
| M04 关系健康度 | 🟡 部分 | 邮件频率分析；完整版尚未上线 |
| M05 费用识别 | ✅ 生产 | 邮件附件识别收据 / 发票 |
| Teams Bot (Audrey) | ✅ 生产 | 1:1 推送 + AI 对话 |
| CRM | ✅ 生产 | 自动从邮件构建联系人库 |
| Dashboard | ✅ 生产 | Web UI 看所有 section 结果 |

---

## 2. 我们能承诺的（partner 可以对外说）

### 2.1 运营承诺

| 维度 | 可承诺 | 注释 |
|---|---|---|
| Uptime | 99% 商务时间 / 95% 24/7 | 单 instance，无 HA |
| Bug 响应 | 24h 内 acknowledge | Business hours (北美) |
| Critical fix | 72h 内 patch | 影响核心功能的 bug |
| Support 渠道 | Email + Teams + WhatsApp | 不承诺 24/7 oncall |
| 数据 residency | 客户选（SaaS=US, BYOC=客户选） | |
| 删数据 | 客户请求后 **7 天内** 完成 | 含备份 |
| 数据 portability | 客户可导出所有数据（JSON） | 1 天准备 |

### 2.2 安全承诺（partner 遇到客户问就念）

| 客户问 | 标准回答 |
|---|---|
| 数据在哪？ | "你选：SaaS 在我们 Railway (US region)；BYOC 在你的 Azure 任意 region。" |
| 谁能看？ | "运营时只有 vendor 团队（Jason + partner）。所有访问有 Azure audit log 记录。" |
| 加密吗？ | "传输 TLS 1.3，存储默认 Azure SSE 加密（AES-256）。" |
| 第三方调谁？ | "Microsoft Graph（你 OAuth 授权访问邮件 / 日历）+ Google Gemini（AI 处理）。其他没有。" |
| 离开怎么办？ | "随时撤销 OAuth，邮件通知我们删数据，7 天内完成。" |
| 你看我数据吗？ | "不会主动看。debug 时需要访问会先告知你。" |
| 有 SOC2 吗？ | "目前没有（早期阶段）。如果你是大企业，我们可以评估 SOC2 timeline。" |

### 2.3 **绝对不能承诺**的（partner 一定要避免）

| 客户问 | 不要承诺 | 替代说法 |
|---|---|---|
| 99.9% uptime | ❌ | "99% 商务时间是当前目标" |
| 数据**永远**不离开客户 cloud | ❌ | "调 Gemini AI 时邮件正文经过 Google（in-transit only），其他全程不出客户 cloud" |
| SOC2 / ISO 27001 / HIPAA | ❌ | "没有，未来视客户需求评估" |
| 24/7 phone support | ❌ | "business hours + 24h response" |
| GDPR 完全合规 | ❌ | "技术架构支持 GDPR，但未做完整合规审计" |
| 自动备份 / disaster recovery | ❌ | "Azure 默认 daily snapshot，恢复需手动" |

---

## 3. 三种 Deployment 选项

### Option A — SaaS（我们 host）

| | |
|---|---|
| **客户体验** | 5 分钟 Microsoft 登录，立刻能用 |
| **数据位置** | 我们 Railway (US-east region) |
| **代码位置** | 我们 Railway |
| **价格区间** | $50-300/月/用户 |
| **典型客户** | 不在乎数据位置 / 试用 / 小公司 CEO |
| **销售周期** | 1-2 周 |
| **客户责任** | 几乎无 |
| **vendor 责任** | 全部 |

**Partner pitch**: "5 分钟开通，月付，随时取消"

### Option B — BYOC（客户 Azure）

| | |
|---|---|
| **客户体验** | 我们一起 setup 1-2 周，之后跑在客户 cloud |
| **数据位置** | 客户 Azure（任意 region） |
| **代码位置** | 客户 Azure（可见） |
| **价格区间** | $500-3000/月/客户 |
| **典型客户** | 数据敏感 / 已有 Azure / 中等规模公司 |
| **销售周期** | 1-2 个月（含合同） |
| **客户责任** | 提供 Azure subscription + 付 Azure 账单 |
| **vendor 责任** | 软件 + 部署 + 运维支持 |

**Partner pitch**: "你的数据进你自己的 Azure，我们部署 + 维护"

**前置条件**：
- 客户必须有 Azure subscription（或我们帮他开）
- 必须签 MSA + NDA + IP + DPA（律师起草，~$3-5k 一次性）

### Option C — Hybrid (CP/DP 分离)

| | |
|---|---|
| **客户体验** | 同 BYOC |
| **数据位置** | 客户 Azure |
| **代码位置** | 关键 IP 在我们 cloud（CP），执行器在客户 |
| **价格区间** | $3000+/月（custom） |
| **典型客户** | 大企业 / 强 IT / 合规要求 |
| **销售周期** | 3-6 个月 |
| **vendor 责任** | SaaS + 客户 deployment 双重维护 |

**Partner pitch**: **暂时不要 pitch 这个 tier**——产品还没准备好。

---

## 4. 距离每个选项 Production-Ready 多远

### Option A (SaaS) — 距离 **~3-5 天工程**

**已有**：
- ✅ 多租户后端（`.data/{user_id}/` 隔离）
- ✅ Microsoft OAuth 登录
- ✅ 所有模块跑通
- ✅ Railway 部署稳定

**缺**：
- ⬜ 邀请 allowlist 机制（partner 加客户邮箱白名单）
- ⬜ "删除我所有数据" 按钮
- ⬜ Partner-facing admin dashboard（看谁注册 / 谁活跃）
- ⬜ Beta disclaimer banner（"试用版，可能挂"）
- ⬜ 1 页"我们用你哪些数据"说明

**结论**：partner **可以立刻开始 pitch**，技术侧 1 周内补齐。

### Option B (BYOC) — 距离 **~2-3 天工程 + 法律 2-3 周**

**已有**：
- ✅ IPS 部署完整跑通
- ✅ Phase A + B 硬化完成（atomic writes, fail-fast envs, etc.）
- ✅ GitHub Actions auto-deploy
- ✅ Customer onboarding runbook 草稿（`docs/deployment-mode-3-byoc.md`）

**缺**：
- ⬜ Onboarding runbook 精修（基于 IPS 经验更新）
- ⬜ Diagnostic bundle endpoint（debug 用）
- ⬜ GitHub Actions 参数化（支持多客户 secrets）
- 🔴 **MSA / NDA / IP / DPA 律师起草**（~3 周，~$3-5k）

**结论**：技术 2-3 天，法律 3 周。Partner 可以开始 pitch，第 2 客户**最早 3 周后上线**（卡在合同）。

### Option C (Hybrid) — 距离 **~1-2 个月**

**已有**：无（设计文档在 `docs/deployment-mode-4-control-data-plane.md`）

**缺**：全部
- ⬜ CP server（你自己 cloud 上跑的 SaaS）
- ⬜ DP runtime 改造
- ⬜ Skills / config 拉取协议
- ⬜ Cache 策略
- ⬜ License + telemetry
- ⬜ Cross-plane debug 工具

**结论**：**partner 6 个月内不要 sell 这个**。等 BYOC 客户 ≥ 5 个、且至少有 1 个客户明确要求"prompt 不可见"时再启动。

---

## 5. 价格 anchor（partner 参考）

| Tier | 月费起步 | 一次性 setup | 上线时间 |
|---|---|---|---|
| **A. SaaS** | $200/月/用户 | $0 | 5 分钟 |
| **B. BYOC** | $1500/月 | $2000-5000 (含 setup + 合同) | 2-4 周 |
| **C. Hybrid** | $5000+/月 | custom | 不接 |

**discount 策略**：
- 年付 -15%
- 早期 design partner 折扣 50% 第一年（换 case study + feedback）
- 推荐分成 partner

---

## 6. Case Study (Daniel/IPS) — 可引用的数据点

> ⚠️ **需要 Daniel 同意后才能对外用**

| 数据点 | 可说 |
|---|---|
| 客户类型 | CEO of consultancy (~50 人公司) |
| 部署模式 | BYOC (在客户 Azure) |
| 使用时长 | [TODO: 填月数] |
| 每日早报 | 自动推送，邮件 + 会议综合 |
| 邮件处理 | 30 天扫描，AI 分类，草稿生成 |
| 会议 | OneDrive 录音自动转录 + action items |
| 节省时间 | [TODO: 跟 Daniel 确认实际数字] |

**对外宣传文案模板**：
> "一个 50 人 consultancy 的 CEO，BYOC 部署在自己 Azure。
> 每天早 7 点收到 AI 早报，邮件自动分类 + 起草，会议录音自动摘要。
> 每天节省 [X] 小时。"

---

## 7. Partner 销售常用问答（FAQ）

| 客户问 | 标准回答 |
|---|---|
| "多久能用上？" | "SaaS 5 分钟，BYOC 2-4 周（含合同）" |
| "我能试用吗？" | "可以，SaaS 模式 14 天免费试用" |
| "我的数据安全吗？" | "[安全 talking points 见 2.2]" |
| "你们竞品是谁？" | "目前没有专门给 CEO 个人的 AI 助理，类似 ChatGPT + 邮件助手组合的简化版" |
| "如果我不喜欢？" | "随时取消，7 天内删除所有数据" |
| "我能加我团队吗？" | "目前单 CEO 模式，团队功能 2026 Q3 roadmap" |
| "支持中文吗？" | "支持，AI 输出可配置语言" |
| "支持 Google Workspace?" | "目前只支持 Microsoft 365，Google 在 roadmap 上但无 timeline" |
| "你们多大？" | "早期阶段，2 人核心团队（Jason 技术 + Partner 商务），适合 high-touch 服务" |
| "公司在哪？" | "[填] 注册地 + 数据 region" |

---

## 8. 销售红线（partner **不能**做的事）

- ❌ 不能承诺"完全的"数据不出客户 cloud（Gemini 调用经过 Google）
- ❌ 不能承诺 SOC2 / HIPAA / ISO 27001
- ❌ 不能承诺自定义功能开发 不收 setup fee
- ❌ 不能 pitch Hybrid tier（还没做出来）
- ❌ 不能签 BYOC 合同前未经律师 review
- ❌ 不能承诺与现有 SaaS (Salesforce / HubSpot 等) 直接集成（roadmap 但无 timeline）
- ❌ 不能承诺 Mobile app（不在 roadmap）
- ❌ 不能 over-promise uptime（看 §2.1）

---

## 9. Partner 工具链交付清单（technical 侧做的事）

partner 真正在用之前，technical 侧需要交付：

| # | 产物 | 状态 | ETA |
|---|---|---|---|
| 1 | Demo 账号 + 假数据 | ⬜ | 1 天 |
| 2 | Demo 一键 reset 功能 | ⬜ | 半天 |
| 3 | 邀请白名单机制 | ⬜ | 半天 |
| 4 | 删账号按钮 + 后端 cleanup | ⬜ | 1 天 |
| 5 | Partner admin dashboard | ⬜ | 1-2 天 |
| 6 | Beta disclaimer banner | ⬜ | 1 小时 |
| 7 | "我们用你哪些数据" 1 页说明 | ⬜ | 1 小时 |
| 8 | 客户支持渠道（Slack channel） | ⬜ | 1 小时 |
| 9 | BYOC onboarding runbook 精修 | 🟡 草稿在 | 半天 |
| 10 | Diagnostic bundle endpoint | ⬜ | 半天 |

**总计 ~4-5 天工程**。完成后 partner 有完整 SaaS + BYOC 销售工具链。

---

## 10. 谁负责什么（分工边界）

| 任务 | Partner | Jason (technical) |
|---|---|---|
| 找客户 / 引荐 | ✅ | ❌ |
| 第一次 discovery call | ✅ | ❌ |
| Demo（用 demo 账号） | ✅ | 可选旁听 |
| 报价 / 合同谈判 | ✅ | ❌ |
| 律师协调 | ✅ | ❌ |
| Trial setup（SaaS 模式邀请白名单） | ✅（用 admin dashboard） | ❌ |
| Trial 期客户跟进 | ✅ | ❌ |
| BYOC 部署（技术执行） | ❌ | ✅ |
| 客户技术问题 | 转给 Jason | ✅ |
| 产品 bug / 新功能 | 收集 → 转 Jason | ✅ |
| 客户续费 / upsell | ✅ | ❌ |
| Case study / 市场材料 | ✅ 主导 | 提供截图 / 数据 |

---

## 11. 沟通节奏建议

| 频率 | 内容 |
|---|---|
| 每周 | Partner + Jason 同步会（30min）：sales pipeline + tech ETA |
| 每月 | 产品 roadmap review + pricing 调整 |
| Ad-hoc | 客户技术问题、紧急 bug |

---

## 关键参考文档

- BYOC 详细：`docs/deployment-mode-3-byoc.md`
- Hybrid 详细：`docs/deployment-mode-4-control-data-plane.md`
- 部署架构：`CEO_platform_v2/CLAUDE.md` "部署：Railway + Azure 双轨"
- Phase A/B 已完成改动：`~/.claude/plans/phase-code-azure-phase-a-purring-pumpkin.md`
