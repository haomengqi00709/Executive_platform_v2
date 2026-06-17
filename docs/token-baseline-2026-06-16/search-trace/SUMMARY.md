# company_intelligence 搜索扇出实测 — 2026-06-16

模型 gemini-2.5-flash · 账号 cd2162aa · 15 家公司 · 一次完整运行

- grounded 调用: 5 次
- **底层真实搜索查询: 96 条**
- **平均扇出: 19.2 条/调用**
- 每次调用条数: [35, 10, 15, 6, 30]

根因: general prompt 让模型「每公司 × 每信号维度」各搜一条(5 家 × 7 维度 = 35 条/次调用)。
满配 25 家公司 ≈ 160 条/次运行 → 在 3.5 上 × 每天多 briefing + 超时重搜 = 账单 $25.75 search。

完整每条查询见 company_intel_2.5flash_search_log.jsonl。
