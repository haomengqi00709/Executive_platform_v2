# Token 测量方法论 — 最准确的做法是"三源分工"

> 最后更新 2026-06-16。配套代码:`src/modules/token_usage.py`、`src/ai.py`、`scripts/measure_tokens.py`、
> `scripts/key_usage.py`、`scripts/reconcile_usage.py`。成本事件背景见 `gemini-cost-incident.md`。

## 一句话结论

**没有"一种方法测准所有 token/成本"。** 不同的东西必须用不同的来源测,各有各准、各有各的盲区:

| 测什么 | 唯一/最准来源 | 实时? | 为什么只能用它 |
|---|---|---|---|
| 单次调用 input/output/**thinking** token | `usage_metadata`(**我们的计量器**) | ✅ | 是 Google 每次调用返回的数;抓到就准(实测 3.5 output 77,755 与 GC **完全一致**) |
| **按 feature 拆**(哪个功能花了多少) | **只有我们的计量器**(`usage_context` tag) | ✅ | GC / SKU 都不按功能拆 |
| 全量用量真值(含失败/超时/绕过的调用) | **GC Cloud Monitoring** | 近实时(分钟) | 服务端记账,捕获所有调用——包括我们计量器漏的 |
| 2.5 的 search query 数 | 响应 `grounding_metadata.web_search_queries` | ✅ | 2.5 每次都回报(实测 72 条) |
| **3.5 的 search query 数(扇出)** | **只有 SKU 账单** | ❌ 滞后 ~1 天 | 3.5 不回报 query(6 次只回 1 次);GC 只给"请求数"不给"query 数" |
| 最终的钱($) | **SKU 账单** | ❌ 滞后 ~1 天 | 唯一权威计费;`aistudio.google.com/spend` 近实时但**对 search 偏低** |
| 失败/超时调用的 token | **只有 GC / SKU** | — | 响应没回来 → 本地没有 `usage_metadata`,**不可恢复** |

**所以"最准的方法" = 修好的计量器(实时 + 按 feature)⊕ GC(全量标尺)⊕ SKU(真钱 + 扇出),三者各管一段、定期对账。**

---

## 三个来源详解

### 1. 我们的计量器(`token_usage.py` + `ai.py`)— 实时、按 feature,但有盲区

- **怎么记**:每次 Gemini 调用后 `_record_usage` 读响应的 `usage_metadata`(prompt / candidates / total),按 `usage_context(feature, uid)` 归类,写 `.data/_ops/token_usage.json`。
- **准在哪**:每一次"抓到的"调用,token 数就是 Google 自己的数,精确。
- **2026-06-16 修了三个让它少算 ~27% 的问题**:
  1. `cost_usd` 现在按 **`total − prompt`** 计 output(= candidates + **thinking**)。之前只算 candidates,漏掉 thinking——而 thinking 占 token 的 ~49% 且按 output 价计费,所以旧公式把 output 成本少算近一半。
  2. **分模型计价**(`_MODEL_PRICING`):2.5(in $0.30/M·out $2.50/M·search 按请求 $35/1000)vs 3.5(in $1.50/M·out $9/M·search 按 query $14/1000)。`record()` 现在带 `model`。
  3. **覆盖了之前绕过计量的 ~15 个调用点**:`transcribe_audio/video`、`expenses`、`bulk_loader`、`outreach`、`m03` 20分钟 fallback、`tools.py` 搜索(新增 `AIClient.record_external_usage`)。
- **仍有的盲区(不可消除)**:
  - **失败/超时调用**:没响应 → 没 `usage_metadata`。只 log(`record_failure`)提示"这里有未计量调用",金额只能靠 GC。
  - **3.5 的 search query**:API 不回报,本地永远只能拿到"请求数",query 数要靠 SKU。3.5 的 search 成本因此在 `cost_usd` 里是**估算** = `请求数 × GEMINI_SEARCH_FANOUT × $0.014`(默认 15,用 SKU 校准)。

### 2. GC Cloud Monitoring — 服务端用量真值(`scripts/key_usage.py`)

- 用 `gcloud auth print-access-token` + Monitoring REST API 拉。
- 关键指标:
  - `generate_content_usage_output_token_count`(by model)— **可信的 output(含 thinking)**。
  - `quota/generate_content_search_request_usage/usage`(by model)— search **请求数**(注意:不是计费 query 数)。
  - `quota/generate_content_paid_tier_2_input_token_count/usage` — input,**口径偏高、算钱不可信**(掺缓存/上下文重复;实测 16M vs SKU 计费 640K)。input 的真值看 SKU。
- **准在哪**:捕获所有调用(含我们漏的)。**不准/不能**:不按 feature 拆;search 只给请求数;input 口径不准。

### 3. SKU 账单 — 真钱 + 真 query 数,但滞后

- 位置:Cloud Billing 报表(按 SKU 分组);**和 `aistudio.google.com/spend` 不是同一处**。
- 滞后 ~1 天,且报表里常带 **Forecast**(预估,会偏高)——看 actual,不要看 forecast。
- **唯一**能给:3.x 的真实 **search query 数**(= 扇出后的计费单位)和最终 $。
- ⚠️ **AI Studio spend 的坑**:它近实时(只在跑的时候动),但**对 search 偏低**——search 的 query 计费要到 SKU 才结算完整。所以 AI Studio 看到的当日金额会比 SKU 最终值低,差的几乎全是 search。**算 search / 最终 $,认 SKU。**

---

## 怎么对账(`scripts/reconcile_usage.py`)

```
python -m scripts.reconcile_usage --project <PROJECT> --hours 24 \
    [--sku-search-usd 25.75] [--sku-search-queries 1839]
```

它做三件事:
1. **meter vs GC 的 output 差额** = 覆盖缺口%(同一窗口、同一 project 下,差额应≈失败调用)。
2. **按 model 的 token $**(GC 用量 × 官方价)。
3. **扇出校准**:给一个 finalized SKU 日的 search($ 或 query 数),算 `扇出 = SKU query ÷ GC 3.x 请求`,把结果设进 `GEMINI_SEARCH_FANOUT`,之后计量器对 3.5 search 的实时估算才准。

**干净对账的前提**:meter 和 GC 要覆盖**同一批调用**——即在隔离 key 上用 `scripts/measure_tokens` 跑,再拉**同一 project、同一时间窗**的 GC;SKU 的窗口要对齐**账单日(Pacific)**,不是 UTC 日。

### 升级项:开 BigQuery billing export(可选,一次性)

无 BQ export 时,SKU 只能靠 console 手抄(还带 forecast)。开 [Cloud Billing → BigQuery export] 后,SKU 的已结算 $ 和 query 数可程序化拉,`reconcile_usage.py` 就能全自动三源对账、不用手贴。

---

## 已知的不可消除缺口(诚实边界)

1. **失败/超时调用** — 本地拿不到 token,只 GC/SKU 有。
2. **3.5 的 search query 数** — 本地永远只有请求数;query 数 = SKU(或用校准过的扇出估)。
3. **当日最终 $** — SKU 滞后 ~1 天;当日只能用 GC 用量 × 官方价 + 扇出估来近似。
4. **历史逐 feature 拆分** — 6/15 埋点前的无法还原。

> 推论:**"实时知道当天花了多少"只能靠我们的计量器 + GC 估;"权威的钱"永远隔天看 SKU。** 两者都要,不是二选一。
