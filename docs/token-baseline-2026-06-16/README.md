# Token 基线 — 2026-06-16(修复前)

修复 §9 之前的 token 用量基线,用于改完后做 **before/after 对比**。
- 测法:`python -m scripts.measure_tokens runall <uid> 3.0`,每次跑前 `reset`,共 3 次全量。
- 账号:`cd2162aa`(Jason 自己,数据量较小,很多 section 返回 0 项 → 这是**轻量下限**,客户邮箱会更高)。
- 模型:**`gemini-3.5-flash`**(本地默认)。价:官方 USD,input $1.50/M、output(含 thinking)$9/M、search $0.014/次。CAD ≈ ×1.38。
- 原始数据:`raw/tok_run_{1,2,3}.json` + `raw/runall_{1,2,3}.log`。

## 每次全量总量

| run | features | input | output | total | thinking | search | 真实成本(USD) |
|---|---|---|---|---|---|---|---|
| run 1 | 10 | 111,212 | 20,102 | 244,735 | 113,421 | 7 | $1.47 |
| run 2 | 10 | 113,337 | 20,628 | 265,764 | 131,799 | 8 | $1.65 |
| run 3 | 9 | 51,163 | 10,366 | 131,077 | 69,548 | 6 | $0.88 |
| **合计** | | 275,712 | 51,096 | 641,576 | 314,768 | 21 | **$4.00** (≈ $5.5 CAD) |

> run 3 较轻 = 增量缓存/去重在重复跑时生效(commitments 缓存、intel 7 天去重、projects 增量)。
> `crm_refresh` 三次都 ≈ $0(增量、无新联系人,被跳过)——本次不是它的锅,但首建/有新数据时会很贵。

## 每个功能 平均成本/次(真实,含 thinking,降序)

| 功能 | avg real$ (USD) | avg total token | avg thinking |
|---|---|---|---|
| **projects_refresh** | 0.485 | 99,981 | 37,504 |
| **company_intelligence** | 0.320 | 35,618 | 24,763 |
| **market_intelligence** | 0.297 | 36,657 | 22,653 |
| reply_needed | 0.105 | 22,580 | 7,925 |
| relationship_health | 0.090 | 17,277 | 6,486 |
| commitments_extract | 0.083 | 15,213 | 7,099 |
| ai_summary | 0.058 | 7,976 | 6,017 |
| followup_needed | 0.026 | 5,311 | 2,331 |
| business_insights | 0.021 | 3,780 | 1,891 |
| yesterday_recap | 0.010 | 2,789 | 751 |

前 3 名(projects + 两个 intel)≈ 真实成本的 ~70%;三个都是 thinking 大户,两个 intel 还叠搜索。

## ⚠️ 这是计量器的数(偏低 ~30%)

同一窗口,**计量器记 output 366K,Google telemetry 实际 498K** → 计量器低估约 27%(差额=超时 grounding 调用不记录)。
所以**真实成本比上表更高**;Google 端口径下这 3 次窗口 ≈ $5.5 CAD。改完计量器(记 thinking + 失败调用)后此基线会更准。

完整事件分析见 [`../gemini-cost-incident.md`](../gemini-cost-incident.md)。
