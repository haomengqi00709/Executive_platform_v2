# 2.5 vs 3.5 实测对比 — company_intelligence(2026-06-16)

**同一输入、同一账号、同一隔离 key/project,各跑一次完整 `company_intelligence`**(15 家公司,3 批,每批 general+social 两次 grounded 调用)。
- 账号:`cd2162aa`(Jason);key:`local_test_key`(UID `aeff0cf3`);project `168552037856`(隔离,单独计费)。
- 每次跑前 `reset` + 清 `company_intel_seen.json`(去重历史)→ 两边公平同起点。
- 模型:`gemini-2.5-flash`(90s 超时) vs `gemini-3.5-flash`(180s 超时,让它跑完不超时)。
- 原始数据:`raw/{2.5,3.5}_token_usage.json` + `raw/{2.5,3.5}_search_log.jsonl`。

## 数字(实测)

| 指标 | 2.5-flash | 3.5-flash | 3.5/2.5 |
|---|---:|---:|---:|
| input token | 9,302 | 10,795 | 1.16× |
| output token(candidates) | 8,274 | 7,331 | 0.89× |
| **thinking token** | **47,069** | **70,424** | **1.50×** |
| 计费 output(=total−input,含 thinking) | 55,343 | 77,755 | 1.40× |
| grounded 调用数 | 6 | 6 | 1.00× |
| **能 trace 到的 web_search_queries** | **72**(6/6 调用都报) | **7**(只 1/6 调用报) | **0.10×** |
| 最终产出 items | 10 | 17 | 1.70× |

## 成本(官方 list price,USD)

价:2.5 = input $0.30/M · output(含thinking) $2.50/M · search **按 grounded 请求** $35/1000(1500/天免费)。
3.5 = input $1.50/M · output(含thinking) **$9/M** · search **按底层 query** $14/1000(5000/月免费,Gemini3 共享)。

| | 2.5-flash | 3.5-flash |
|---|---:|---:|
| input | $0.0028 | $0.0162 |
| output(含thinking) | $0.1384 | **$0.6998** |
| **compute 小计** | **$0.1411** | **$0.7160**(**5.07×**) |
| search(只算能看到的) | $0.2100(6 请求) | $0.0980(7 query) |

> **compute(input+output)3.5 是 2.5 的 5.07 倍**——这是确定的、与搜索无关的部分。
> 主因:output 单价 3.6×($9 vs $2.5)× 3.5 多烧 50% thinking。

## 两个关键结论

### 1. 3.5 的搜索从我们这端几乎 trace 不到(账单谜团的解释)
- **2.5**:6 次 grounded 调用,**每次都在 `grounding_metadata.web_search_queries` 里返回真实 query 列表**(共 72 条),完全可追溯、可与 search SKU 对账。
- **3.5**:同样 6 次 grounded 调用,**只有 1 次返回了 query(7 条),其余 5 次返回空**。
- probe 证实 2.5 的 `web_search_queries` 字段稳定填充(单次 probe = 9 条 + 23 个 grounding_chunks);3.5 的 re-probe 撞 **429 free-tier quota 耗尽**,暂未拿到 3.5 的字段结构。

**这正是「Google 记 1000+ search,我们 log 里却看不到」的根因**:6/2 起生产跑在 3.5,而 3.5 大多数 grounded 调用**不回传** `web_search_queries`,服务端照样扇出并按 query 计费 → 我们的埋点几乎记不到搜索。

⚠️ **诚实边界**:3.5 的 5 次空 query,目前无法 100% 区分是
(a) **搜了但不回报 query**(→ 隐形扇出计费,账单谜团) 还是
(b) **根本没搜、用模型自身知识答**(→ 时效性风险)。
本次 validator 恰好删了 3.5 的一条疑似编造人名(`James T.`)和一条 33 天前的过期项 → 暗示至少部分 3.5 item 来自参数化知识而非实时搜索。**两种解释都不利于在本场景用 3.5**:要么隐形烧钱、要么 grounding 不可靠。需补测(换付费 quota 重 probe 3.5 的 grounding_chunks)才能定论。

### 2. 3.5 产出更多 items(17 vs 10),但代价是 5× compute + 不可追溯 + 需更强 validator
3.5 这次产出 17 条(validator 19→17),2.5 产出 10 条(validator 14→10)。
"更多" 不等于 "更好":多出来的部分恰恰是 validator 需要额外把关的(编造/过期)。

## 结论指向
换回 **2.5-flash**:① compute 便宜 5×;② 搜索 1500/天免费且**按请求计费**(扇出再多也不翻倍),而 3.5 按 query 计费且扇出隐形;③ 搜索完全可追溯,能持续对账。
代价是 items 略少 + 偶尔需要把搜索 prompt 写得更明确——可接受。
