# Gemini API 成本事件 — 完整报告(权威版)

> 2026 年 5–6 月 Gemini API 账单异常(~CA$1,483 / 两周)的完整分析。
> 一切可追溯:Google Cloud Monitoring telemetry(31 天逐日逐模型)· Google SKU 账单 ·
> 应用源码 · git history · Railway/Azure 日志 · 4 次本地实测。
> Part 1 中文(给团队);Part 2 English(可直接用于 Google 账单申诉)。
> 最后更新:2026-06-16。

---

# Part 1 — 中文

## 0. 一句话

**两波叠加 + 全程没有可信的"秤"。**
① **5/22 v2 上线** → token 量翻 ~15 倍(但当时跑在便宜的 `gemini-2.5-flash`,钱还没爆);
② **6/1 一个 commit(`06a122a`)把默认模型翻成 `gemini-3.5-flash`** → 6/2 起同样的海量 token 按贵模型计费 → 两周 ~CA$1,483。
而**应用的 token 计量系统性低估、且多处调用根本不计**,所以一直没人发现,直到撞上月度消费上限。

## 1. 账单事实(Google SKU,精确数字)

| 计费项 | 用量 | 金额 |
|---|---|---|
| 输出 token(gemini-3.5-flash) | 53,335,349 | $663.79 |
| 输入 token(gemini-3.5-flash) | 214,711,416 | $445.37 |
| 网页搜索接地查询 | 9,129 次 | $176.74 |
| 输入音频(会议转录) | 947,585 | $1.97 |
| 其他(2.5-flash short / image) | — | <$10 |

5/16–6/14 共 **CA$1,482.79**(上月仅 ~$52,**+2,757%**)。钱几乎全在**文本生成 + 网页搜索**;
**会议转录只花 $1.97,与本次无关**。
注意:贵的部分(output $663 + input $445)**全部记在 `gemini-3.5-flash`**;`gemini-2.5-flash`
的用量落在 "<$10" 那行 —— 这是下面"模型翻新"根因的**账单铁证**。

## 2. 真实时间线(Google telemetry 每日 output token = 真相,非滞后账单)

```
5/15–5/19   ~25 万/天     正常（v2 未上线）
5/22         220 万/天     ← v2 上线，量暴涨（仍 2.5-flash → 便宜）
5/24         470 万/天
6/02         全量切 3.5-flash  ← 价格暴涨，钱开始真烧
6/05         560 万/天     峰值（~$50/天）
6/14         440 万/天
6/15          82 万/天     ← 锁 cap
```

**逐日逐模型拆分(Google telemetry):** 5 月几乎全是 `gemini-2.5-flash`;**6/2 起 100% `gemini-3.5-flash`**。
> 31 天合计:input **407M**、output **96M**(其中 56M 在 3.5-flash、40M 在 2.5-flash)、search **1,232**、
> 请求 200 成功 / 429 被 cap 挡。

## 3. 两个根因(git 实锤)

**根因 A — 量:v2 上线(5/21–5/23)**
- `7915e58` "Build out v2: 17 sections, briefings, Records page"
- `b898c42` "16-tool agentic bot" + `1ce1c04` session context
- 17 个 section 按 schedule 跑 + 每日简报 + agentic bot,每次吞大量上下文。日 token 25 万 → 470 万。
- **但当时用便宜的 `gemini-2.5-flash`,所以钱还没爆。**

**根因 B — 价:模型翻新(6/1,commit `06a122a`)= 真正的钱**
```diff
- self.model = "gemini-2.5-flash"
+ DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
```
6/2 起全量切 3.5-flash。**实证对比:5 月(2.5-flash,量已很高)几乎不花钱;6 月(3.5-flash,同等量)
花了 ~$1,200 —— May→June 的差别主要就是模型。**

> **量 × 价 = 爆炸。** 单独任一个都不致命。

## 4. 为什么"积累成指数曲线"(架构层)

平台**自动发现并永久累积**每个用户的联系人 / 公司 / 项目;定时任务随后**每天把整个变大的集合
全量重算、零增量缓存**:
- **Projects 重建**(每天 06:30,每用户):回看 45 天、最多 500 封,每天整批重过 AI(`src/modules/projects.py`)。
- **CRM 重建**(每天 06:00,每用户):逐个联系人调 Gemini(最多 200);改一次 prompt 版本会把全部重富化。
- **情报搜索**:每家公司每次重搜;`intel_dedup`(`*_seen.json`)只对【结果标题】去重,**从不跳过任何一次搜索** → 对省钱零帮助。
- **input 是最大 token 块(407M)** —— 就是这些"每次重吞海量上下文"。

**两条同时增长的轴(单用户数据越攒越多 × 用户越来越多)相乘 → 指数曲线。**

## 5. 放大缺陷(源码 verify)

1. **搜索空响应重试**:`src/ai.py` `generate_with_search` 对空响应重试,每次都是一笔计费搜索 → 9,129 里很大一块是"空搜索重发"。
2. **429/cap 重试重发**:旧代码只匹配字面 `"429"`,放过 `RESOURCE_EXHAUSTED`,整段重发 3–4 次(仍计费)。
3. **校验双跑**:~11 个 section 各多跑一次完整 Gemini 调用(`src/modules/validator.py`),成本≈翻倍。
4. **多部署叠加**:同一调度器曾同时跑在 Railway + Azure + 一台跑了 10 天的本地 server,各自遍历全部 session。

## 6. ⭐ 我们的 token 计量 vs Gemini 实际计费(核心问题)

**结论:不一样 —— 系统性低估。5 个具体差异(均源码 verify):**

1. **漏 thinking token**:`src/modules/token_usage.py` 的 `cost_usd` 只算 `prompt + output(candidates)`,
   **不加 thinking(= total − prompt − candidates)**;而官方 output 价**含 thinking token**。
   计量器其实**记录了 total,但 cost_usd 没用它** → 漏掉约一半 output 计费。
2. **多处调用完全不计**:`AIClient.transcribe_audio/video`、`src/tools.py`(还硬编码 `gemini-2.5-flash`)、
   `src/sections/expenses.py:175`、`src/modules/bulk_loader.py:222`、`src/modules/outreach.py:94/136`、
   `src/modules/m03_meeting.py:683` 都直接 `client.models.generate_content(...)`,**绕过 `_record_usage`**。
   (`src/bot.py` 有自己单独的 `_record_bot_usage`,会算,但归在 "bot" 标签下、与主计量器分离。)
3. **失败 / 超时 / 空响应 / 429 不计**:`_record_usage` 只在成功路径调;但超时那些**服务端已经算完、Google 照样计费**。
4. **单一 blended 价、不分模型**:`usage_metadata` 不含模型名,计量器也不记 → 2.5 vs 3.5 价算错,**也没法和账单逐项对账**。
5. **搜索按固定 $/次**(`USD_PER_SEARCH`),不计搜索本身产生的 token。

**实证(4 次本地实测 vs Google telemetry):** 我 3 次 run,计量器记 output **366K**,**Google 实际 498K(低估 ~27%)**;
计量器显示 **$0.65/次**,**真实 ~$2/次**。差额 = 超时的 grounding 调用(服务端计费、客户端丢弃、计量器不记录)。

> ✅ **2026-06-16 已修 1/2/4/5**:`cost_usd` 改用 `total − prompt` 计 output(含 thinking);分模型计价;覆盖了
> transcribe/expenses/bulk_loader/outreach/m03/tools 等绕过点;search 按模型(2.5 按请求、3.5 按 query × 校准扇出)。
> **3 仍是不可消除盲区**(失败/超时无 `usage_metadata`),只能 log + 靠 GC。完整方法论见
> [`token-measurement-method.md`](token-measurement-method.md),三源对账脚本 `scripts/reconcile_usage.py`。

## 7. ⭐ 一直在烧 token 的地方(自动 / 持续,按影响排序)

| 源 | 频率 | 浪费? | 说明 |
|---|---|---|---|
| 邮件 screener 重扫 | 1 分钟 | 是 | 每轮把可见收件箱重过一遍,**无 per-email 缓存** |
| 简报跑全部 section | per-user cron(常同点) | 是 | 一次简报 ~15–25 次 Gemini;所有用户同点触发风暴 |
| **validator 双跑** | 每个 section | 是 | 主调用 + 校验调用 = 2× |
| 全量重吞上下文 | 每次 run | 是 | reply_needed 14 天、projects 45 天、relationship 全量,**无增量** |
| CRM 逐联系人富化 | 每天 | 是 | 最多 200,每轮 ~30 次调用 |
| projects 逐项目重评 | 每天 | 是 | 每项目 1 次 + 筛选 |
| bot agentic 循环 | 每条消息 | 是 | `MAX_ROUNDS=12`,简单问题也可能跑满 |
| **intel 搜索 60s 超时→重试** | 每次情报 | 是 | 双倍计费、0 产出 |
| 空响应重试 = 重计费 | 各处 | 是 | 同一 prompt 重发 |
| meeting_prep / expense / recordings 轮询 | 5m / 1m / 20m | 视量 | 有新数据才烧 |

**共性浪费**:无增量缓存、校验双跑、空响应重发、简报同点风暴、多部署叠加。

## 8. 为什么一直没发现

6/15 之前**根本没有 token 日志**;计量器**只在成功时记、且对其它部署失明**;
**Google 账单显示滞后 ~1 天**(让你误以为"跑的时候才烧");多部署共用一个 key。

## 9. 修复(按省钱优先级)

1. **不需要 3.5 的 section 换回 `gemini-2.5-flash`** —— 最大杠杆(整个 5 月证明 2.5 够用)。
2. **砍 input 量**:增量 / 缓存 / 缩小上下文,别每次全量重扫(407M input 是最大块)。
3. **`thinking_budget=0/低`** —— 砍掉约一半 output token。
4. **修计量器**:`cost_usd` 用 total 算 thinking + 覆盖所有调用点 + 记失败调用 + 记模型名。
5. **搜索层真缓存**(跳过搜索,而非只去重结果)+ 修 intel 60s 超时。
6. **validator 抽样 / 合并、简报错峰、bot 减轮次。**
7. **单部署 + 应用层每日预算熔断**(别只靠 Google cap 硬刹)。

**已做:** ① 月度 cap(已拦截);② 按功能 token 记账上线;③ retry 修(搜索空响应不再重试、quota/cap 判为 fatal、4→2 次);
④ 三处带 key 的部署止血(本地 server kill;Railway + Azure 的 `GEMINI_API_KEY` 设 disabled);
⑤ **计量器修准(2026-06-16)**:加 thinking、分模型计价、覆盖 ~15 个绕过点、search 按模型 + 校准扇出、修隔离 bug;
新增三源对账工具 `scripts/reconcile_usage.py` 与方法论 [`token-measurement-method.md`](token-measurement-method.md)。

## 诚实边界

`gemini-2.5-flash` 确切单价、input 在两个模型间的精确拆分**未逐一坐实**(影响的是 5 月那段、本就便宜的部分);
**逐功能的历史拆分因当时无埋点,永远无法 100% 还原** —— 以上是 Google telemetry + git + 源码 + 4 次实测的最佳重建。
**两个根因(量 = v2 上线、价 = 模型翻新)是 git + Google telemetry 双重实锤。**

---

# Part 2 — English (for the Google billing appeal)

## Summary

Billing **May 16 – Jun 14, 2026: CA$1,482.79**, a **2,757% increase** over the prior month
(~CA$52). Cost was negligible until ~May 23, then rose sharply from ~June 1.

## Billing breakdown (Google SKUs)

| SKU | Units | Cost |
|---|---|---|
| Generate content — OUTPUT text, gemini-3.5-flash | 53,335,349 tokens | $663.79 |
| Generate content — INPUT text, gemini-3.5-flash | 214,711,416 tokens | $445.37 |
| Generate content — SEARCH-grounding queries | 9,129 queries | $176.74 |
| INPUT audio (transcription) | 947,585 tokens | $1.97 |
| Other (2.5-flash short / image) | — | <$10 |

Cost is ~entirely **text generation + web-search grounding**; transcription is negligible.

## Root cause

A set of AI features deployed in **late May 2026** runs scheduled background jobs that
**re-process a continuously growing dataset (contacts, companies, projects, email) in full
every day, with no incremental caching**, plus web-search grounding **with no result cache**.
Cost therefore grew with accumulated data × user count (cumulative cost climbed sharply from
~June 1). Software defects amplified it: (1) **search calls that returned an empty result — a
legitimate "no news today" outcome — were retried up to 4×, each re-issuing a billed Google
Search query**, the primary driver of the inflated 9,129-query count; (2) a retry loop that
**re-sent failed requests 3–4×** (still billed) on rate-limit/quota errors; (3) a redundant
**second validation pass** on most outputs. Because **no token-usage monitoring or effective
spend guardrail was in place**, this unintended runaway went unnoticed for ~two weeks until it
reached the monthly spend cap.

## Note on per-feature attribution

Per-feature token attribution for the past is unrecoverable: the application never recorded
per-call token counts, and Google billing breaks down only by SKU (model + token type), not by
application feature. Grounded search ($176.74 / 9,129 queries) comes predominantly from the
Company and Market Intelligence features, with a large fraction being the empty-result retry
defect re-issuing the same query up to 4×.

## Remediation

Completed: monthly spend cap (active); per-feature token accounting; retry fix (search
empty-results no longer retried; quota / spend-cap errors now fatal and never re-sent);
redundant deployments stopped. In progress: web-search caching at the query layer (skip the
search, not just de-duplicate results); incremental (not daily-full) CRM/Projects processing;
and a daily token-budget circuit-breaker.

## Suggested appeal statement

> Our platform deployed a set of AI features in late May 2026. Prior monthly usage was
> negligible (~CA$52/month). These features' background jobs re-process a continuously growing
> dataset (contacts, companies, projects, email) in full every day with no incremental caching,
> and use web-search grounding with no result cache — causing cost to grow with accumulated data
> and user count. Software defects amplified it: empty ("no results") searches were retried up to
> 4× — each re-issuing a billed search query, inflating the search-query count several-fold —
> plus a retry loop that re-sent failed requests 3–4× and a redundant second validation pass.
> Because no token-usage monitoring or effective spend guardrail was in place, this unintended
> runaway went unnoticed for ~two weeks until it reached ~CA$1,482 — a 2,757% spike over the
> prior month. Having identified the root cause, we have set a spend cap and are implementing
> usage monitoring and defect fixes. We respectfully request a one-time adjustment for this
> anomalous, software-defect-driven usage.

---

## 附录:证据来源(可复核)

- **Google 用量(权威)**:`gcloud` + Cloud Monitoring REST,project `gen-lang-client-0448678985`,
  指标 `generativelanguage.googleapis.com/generate_content_usage_output_token_count`(逐日逐模型)、
  `quota/generate_content_search_request_usage/usage`、`serviceruntime.googleapis.com/api/request_count`。
- **模型翻新根因**:`git show 06a122a -- src/ai.py`。
- **v2 上线**:`git log` 5/21–5/23(`7915e58`、`b898c42`)。
- **计量器审计**:`src/ai.py`(`_record_usage`、`generate*`、`transcribe_*`)、`src/modules/token_usage.py`(`cost_usd`)、
  `grep -rn generate_content src/`(绕过点)。
- **实测**:`scripts/measure_tokens.py runall`(4 次全量)+ `.data/_ops/token_usage.json`。
