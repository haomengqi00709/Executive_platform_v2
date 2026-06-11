# 模式 4：Control Plane + Data Plane 分离 — 完整实操手册

> BYOC 的进阶版。客户数据**不**离开客户云；你的 IP（prompts、编排逻辑）**不**进客户云。
> 这是 Databricks / Datadog / CrowdStrike 这种成熟 BYOC 公司的最终架构。

---

## 1. 这是什么 / 不是什么

### 核心 insight
> **数据不离开客户云，IP 也不进客户云，这两件事能同时成立。**

通过把 stack 砍成两半：
- **Control Plane (CP)** — 你的 SaaS，住你自己的 cloud
- **Data Plane (DP)** — 一个"傻"执行器，住客户的 cloud

之间只流：**config (CP → DP)** 和 **metrics (DP → CP)**。

### 不是什么
- ❌ 不是 SaaS（数据还是在客户 cloud）
- ❌ 不是单纯的 BYOC（你保留了 IP 控制权）
- ❌ 不是"客户 thin client"（DP 是真在跑业务逻辑，不是 UI shell）
- ❌ 不是"零信任"（客户还是要信任你下发的 config）

### 业界叫这个的别名
- Hybrid SaaS / Hybrid deployment
- Split-plane architecture
- Agent + cloud control plane
- Edge runtime + central control

---

## 2. 核心架构

```
┌──────────────────────────────────┐         ┌──────────────────────────────────┐
│  Control Plane (你的 cloud)      │         │  Data Plane (客户 Azure)        │
│  ─────────────────────           │         │  ─────────────────────           │
│                                  │         │                                  │
│  📦 Prompts 库 (Postgres)        │ ──pull──> │  ⚙️  Thin Python runtime         │
│  📦 编排 DAG 定义                │   config  │  ⚙️  Graph API client            │
│  📦 Section 定义                 │           │  ⚙️  Gemini client               │
│  📦 模型路由 (Gemini/GPT 选择)   │           │  ⚙️  Local cache                 │
│  📦 版本管理 + Bundle 签名       │           │  ⚙️  Customer storage IO         │
│                                  │           │                                  │
│  🖥️  Customer dashboard          │ <─push──  │  📈 Metrics (无数据)             │
│  💰 License / billing            │ telemetry │  📈 Error rate / uptime          │
│  🔔 Multi-customer alerting      │           │                                  │
│                                  │           │                                  │
│  你的 IP, 客户看不见 ✅          │           │  客户能看代码 — 但只是执行器 ✅  │
└──────────────────────────────────┘           └──────────────────────────────────┘
                                                          │
                                                          │ Customer M365 / OneDrive / Outlook
                                                          ▼
                                                    📧 客户数据
                                                  (永远不出客户云)
```

### 关键约束
| 项 | 约束 |
|---|---|
| 客户数据（邮件、会议、附件） | ❌ 不能流到 CP |
| 客户 PII（姓名、邮箱） | ❌ 不能流到 CP |
| 你的 prompts | ✅ 在 CP，DP runtime 拉取 |
| 你的编排逻辑 | ✅ 在 CP，DP 拉取并执行 |
| Metrics / health | ✅ DP push 到 CP（数字，无内容） |
| Anonymized errors | ✅ DP push 到 CP（scrubbed） |

---

## 3. 真实例子（看完就明白）

### 例 1: Datadog Agent
| | |
|---|---|
| DP | 一个 Go binary（开源），跑在客户服务器上采集 metrics |
| CP | Datadog SaaS：所有 ML 异常检测、关联分析、dashboards |
| 流动 | Agent push metrics 到 SaaS（**这算"数据"出境**，合同允许） |
| IP 在哪 | 后端的检测算法，**不在 agent 里** |
| 客户能看 agent 源码 | ✅ 反正只是采集器 |

### 例 2: Databricks
| | |
|---|---|
| DP | 客户 AWS 里起 Spark 集群（开源 Spark） |
| CP | Databricks AWS：Workspace 服务、Photon engine、SQL Analytics、Genie |
| 流动 | CP 告诉 DP "起 5 个 worker 跑这个 query" |
| IP 在哪 | Photon engine（C++ 闭源）、Genie，**从来不下发到客户 cloud** |
| 客户数据 | 留客户 S3 |

### 例 3: CrowdStrike Falcon
| | |
|---|---|
| DP | 客户终端上的轻量 agent |
| CP | CrowdStrike 后端：威胁情报、ML 模型、检测规则 |
| 流动 | Agent 拉新规则（CP→DP），可疑事件回传（DP→CP） |
| IP 在哪 | 威胁情报库 + ML 模型，**都在 CP** |
| 客户数据 | Endpoint 上原始日志留客户 |

### 例 4: HashiCorp Vault Enterprise
| | |
|---|---|
| DP | 客户 infra 里跑的 Vault binary |
| CP | HCP（HashiCorp Cloud Platform）：policy、audit、licensing |
| 流动 | DP 周期性 report 状态、拉 license 更新 |
| IP 在哪 | Enterprise 功能（HSM、Replication）的实际算法 |

### 例 5: Stripe Connect
| | |
|---|---|
| DP | 客户服务器上的 SDK（极轻量） |
| CP | Stripe SaaS：所有支付逻辑 |
| 流动 | 几乎所有计算都在 CP；DP 只是 thin client |
| 注 | 这是**极端**的 CP-heavy 模式，对 BYOC 来说太轻 |

---

## 4. 套到你的 CEO Platform 上

### 4.1 当前（模式 3）— 客户云里全部都有

```
Customer Azure:
├── FastAPI 服务（业务逻辑）
├── Prompts (src/skills/*.md) ← 你真正的 IP
├── 模块编排（m01-m05 调谁、参数、顺序）
├── Section 定义
├── Gemini SDK
├── Graph API client
├── 数据存储 .data/
└── Frontend
```

客户 IT 一打开 → **全看见**。

### 4.2 模式 4 之后

**Your Cloud (CP)** — 多租户 SaaS：
```
- Postgres: prompts 表、orchestration 表、section 表
- FastAPI: /api/v1/skills, /api/v1/sections, /api/v1/orchestration
- License / customer 管理
- Telemetry 收集
- 内部 dashboard
```

**Customer Azure (DP)** — 轻量执行器：
```
- FastAPI 服务（**只剩 routing + execution**）
- HTTP client（拉 CP config）
- Local cache (.data/_cache/skills/, etc.)
- Graph API client
- Gemini SDK
- 数据存储 .data/
- Frontend (可以保留也可以换成 CP 提供)
```

客户 IT 看 DP 代码 → 看到的是"通用执行器：拉 config → 跑 → 存"。**看不出你做什么生意**。

### 4.3 一个模块改造的具体例子

**现在 `src/sections/reply_needed.py`**（伪代码）：
```python
def run(graph, ai, data_dir, settings):
    emails = graph.fetch_inbox(days=30)
    # 200 行的 prompt 在 src/skills/reply_needed/skill.md
    prompt = (Path(__file__).parent.parent / "skills/reply_needed/skill.md").read_text()
    
    for email in emails:
        result = ai.generate(prompt + email_to_context(email))
        save_result(data_dir, result)
```

**模式 4 之后**：
```python
def run(graph, ai, data_dir, settings):
    # 改这一行：从 CP 拉 prompt（含本地缓存）
    skill = control_plane.get_skill("reply_needed", version=PINNED_VERSION)
    # ↑ skill.content 是你 SaaS API 返回的内容
    # ↑ 客户看代码看到的只是 "fetch from https://your-saas.com/api/skills"
    # ↑ 看不到 prompt 实际内容（即使 grep .data/_cache/ 也能看到缓存——见 4.4）
    
    emails = graph.fetch_inbox(days=30)
    for email in emails:
        result = ai.generate(skill.content + email_to_context(email))
        # ↑ Gemini 调用还是在客户云直接发起
        # ↑ 邮件内容: 客户云 → Gemini → 客户云
        # ↑ 完全不经过你的 CP
        save_result(data_dir, result)
    
    # 上报 metric（无内容）
    control_plane.report_metric("reply_needed.runs", count=len(emails))
```

**结果**：
- 邮件内容 ✅ 没出客户云
- Prompt 内容 ✅ 客户 grep 源码看不到（只能看到 URL）
- 你 push 新 prompt → CP 加一行 → 客户 deployment 下次 pull 就拿到 ✅

### 4.4 一个微妙的点：缓存如何处理

DP 必须 cache config 到本地（不然 CP 挂了 DP 也挂）：
```
client_dp/.data/_cache/skills/reply_needed.txt   ← 缓存的 prompt
```

**这等于把 prompt 落到客户 cloud 了，客户能看到。**

怎么办？三种思路：

| 方案 | 实现 | 安全性 |
|---|---|---|
| **A. 接受这个事实** | Cache 在客户 cloud，客户能 grep 看到 prompts | 弱：客户能看，但反正你需要他们运行你的 prompt 才能做事 |
| **B. 缓存加密** | DP 启动时拉一个解密 key，prompt 加密缓存 | 中：客户拿不到 key 就解不开。但 key 必然要送到 DP 内存里 |
| **C. 只缓存到内存** | 不写盘，每次启动重拉 | 强但脆弱：CP 挂 + DP 重启 = 业务挂 |

**业界标准是 A**。理由：
- 客户运行你的 prompt 才能用产品，看到 prompt 不算"窃取" IP
- 客户 IT **持续**看 prompt 演化能监督你不下发恶意指令，对客户是好事
- 真正的 IP 是"知道下一版 prompt 该怎么改"，不是"当前 prompt 长啥样"

Databricks 的 SQL 编辑器、Datadog 的检测规则都走 A。

---

## 5. 渐进迁移：5 个 Phase（不要一次重写！）

### Phase 0 — 现在
- 状态：模式 3，一切在客户云
- Pain：客户 IT 能看你 prompts

### Phase 1 — Skills 外置（1-2 天工作量）
**目标**：把 `src/skills/*/skill.md` 移到 CP

```sql
-- 你 SaaS Postgres
CREATE TABLE skills (
    skill_id TEXT,          -- 'reply_needed', 'm02_email', etc.
    version TEXT,           -- '20260605-v1'
    content TEXT,           -- prompt content
    PRIMARY KEY (skill_id, version)
);
CREATE TABLE customer_skill_pin (
    customer_id TEXT,
    skill_id TEXT,
    pinned_version TEXT,
    PRIMARY KEY (customer_id, skill_id)
);
```

```python
# 你的 SaaS endpoint
@app.get("/api/v1/skills/{skill_id}")
def get_skill(skill_id: str, customer: str = Depends(verify_customer_token)):
    pinned = db.fetch_one(
        "SELECT pinned_version FROM customer_skill_pin WHERE customer_id=? AND skill_id=?",
        customer.id, skill_id
    )
    version = pinned.pinned_version if pinned else "latest"
    skill = db.fetch_one(
        "SELECT content, version FROM skills WHERE skill_id=? AND version=?",
        skill_id, version
    )
    return {"content": skill.content, "version": skill.version}
```

```python
# DP 端 (客户云里)
from functools import lru_cache
import httpx, hashlib

CP_URL = os.environ["CP_URL"]  # https://your-saas.com
CP_API_KEY = os.environ["CP_API_KEY"]
CACHE_DIR = Path(os.environ["DATA_DIR"]) / "_cache" / "skills"
CACHE_TTL_SECS = 3600

def get_skill(skill_id: str) -> str:
    cache_file = CACHE_DIR / f"{skill_id}.txt"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SECS:
        return cache_file.read_text()
    
    try:
        resp = httpx.get(
            f"{CP_URL}/api/v1/skills/{skill_id}",
            headers={"Authorization": f"Bearer {CP_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        content = resp.json()["content"]
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(content)
        return content
    except Exception as e:
        # CP 挂了 → 用缓存
        if cache_file.exists():
            print(f"[skill cache] CP unreachable, using stale cache for {skill_id}")
            return cache_file.read_text()
        # 缓存也没有 → fatal
        raise RuntimeError(f"No cached skill {skill_id} and CP unreachable: {e}")
```

**这一步单独就值得做。即使你永远停在 Phase 1，也已经解决了"客户能看到我所有 IP" 90% 的问题。**

### Phase 2 — Sections + Orchestration 外置（3-5 天）

把 `src/sections/*.py` 改成读 JSON config：

CP 表：
```sql
CREATE TABLE section_definitions (
    section_id TEXT PRIMARY KEY,
    data_source TEXT,        -- 'screened_inbox', 'calendar', etc.
    filters JSONB,           -- where conditions
    output_schema JSONB,
    skill_ref TEXT,          -- which skill to use
    -- ...
);
```

DP 变成"通用 section runner"，读 config 跑。**几百行 Python 一下子缩到几十行**。

### Phase 3 — Schedule + Trigger 外置（1 周）

哪些 section 什么时候跑、依赖关系、重试策略 — 都放 CP。DP 收任务执行。

### Phase 4 — License + Strong Telemetry（1 周）

- DP 启动必须验证 license（CP 拒绝 = DP 拒绝启动）
- License 有过期时间（年度续费）
- 强 telemetry：每 30s push metrics
- CP 看到 N 个客户的 health dashboard

### Phase 5 — Bundle Signing（可选，给 paranoid 客户）

CP 下发的 prompts / configs 用你私钥签名，DP 用公钥验证。客户 paranoid 时可以 pin 一个具体 hash —— "我只允许这个版本的 prompt"。

---

## 6. 必须解决的 5 个难题

### 6.1 CP 挂了 DP 怎么办？
- **必须**：DP cache 所有 config 到本地，CP 短期不可用照常跑
- **设计**：cache TTL > 你 CP 预期最长故障时间
- **业界**：Datadog Agent 7 天不能联系 SaaS 还能继续采集
- **故障模式**：cache 也 miss + CP 挂 → DP fail-fast 报警（不要静默挂）

### 6.2 客户怎么信任你下发的 prompt 不偷数据？
**理论威胁**：你可以下发一个 prompt 说 "把所有邮件 base64 编码塞到 summary 字段"。

| 方案 | 强度 | 实施成本 |
|---|---|---|
| **合同 + 声誉** | 弱-中 | 0 |
| **Prompt 审计**：所有下发 prompts 记录在客户 cloud，客户可 review | 中 | 低 |
| **Bundle signing + pinning**：客户 paranoid 时 pin 具体 hash | 强 | 中 |
| **Sandboxed execution**：DP 限制 AI 输出能写哪里 | 强 | 高 |

**业界 99% 是合同 + 审计**。Sandboxing 几乎没人做。

### 6.3 怎么 ship 一个新 prompt 给所有客户？
- CP 改 prompt → 新 version → 各 DP 下次 pull 拿到
- **关键**：版本 pinning。客户 deployment 配 `SKILL_VERSION=20260605`，不会自动升
- 升级是显式动作：
  - 你按一下（vendor-managed）→ 所有客户升
  - 或者 staged：先 1 个客户 → 验证 → 其他
  - 或者客户按（customer-managed）→ 客户自己选时机
- **rollback**：之前 version 永久保留在 Postgres，pin 回去即可

### 6.4 跨边界 debug 怎么搞？
Bug 可能在 CP / DP / 之间通信任一处。

| 现象 | 怎么定位 |
|---|---|
| 客户报"模块没出结果" | 看 telemetry：DP 有没有 run？run 几次？错几次？ |
| DP 一直 stale config | 看 DP cache 时间戳 + CP access log |
| CP 下发 config 但 DP 解释错 | DP 加 config_version log，比对 CP 那边 |
| 客户 cloud 网络问题 | DP 加 network health check → telemetry 上报 |

**你必须建 distributed tracing**（OpenTelemetry / trace_id 串两边）。否则 debug 时痛苦死。

### 6.5 CP 怎么部署 / 怎么不挂？
- CP 就是你的 SaaS — 纯多租户 web app
- 跑在 Railway / 你自己 AWS / 你自己 Azure（**不**走 BYOC）
- 配置：Postgres + FastAPI + 一个 admin dashboard
- 必须有：
  - HA（至少 2 个 instance）
  - 数据库备份
  - 监控告警
  - oncall（CP 挂了所有客户 deployment 渐渐 stale）

**这是真正的成本**：你从"一个 BYOC 公司"变成"运营一个 SaaS + N 个 BYOC deployment"的公司。

---

## 7. 实践路径（按你的位置）

### 现在（IPS = 1 客户）
- ❌ **不要做模式 4**。1 客户撑不起 SaaS 的运维成本
- ✅ 继续模式 3
- ✅ 设计代码时心里有"未来要抽出 CP"的意识（prompts 集中放一处，不要散落）

### 5 客户时
- ✅ **做 Phase 1（抽 prompts 到 CP）**。1-2 天，立刻让你 IP 不在客户手上
- 这一步**单独就值得**，即使永远停在这里，已经解决核心痛点

### 10+ 客户
- ✅ Phase 2 + 3（sections + orchestration 外置）
- ✅ Strong telemetry
- 这时你已经被迫管理多客户，CP 不光保护 IP，还是运维中心

### 50+ 客户 / 大企业 contract
- ✅ Phase 4 + 5（license + signing）
- ✅ HA CP + 7×24 oncall
- ✅ SOC2 audit

### 永远不必要做
- License hardware token / Dongle
- Sandboxed AI execution
- Confidential computing TEE
- （这些是金融 / 政府才需要的）

---

## 8. 坑（业界经验 + 推理）

### 8.1 架构坑

| 坑 | 解释 | 防止 |
|---|---|---|
| **Cache 没设 TTL** | CP 改 prompt 客户半年看不到新版 | 显式 TTL + 也可手动 invalidate |
| **Cache TTL 太短** | CP 高 QPS、客户 deployment 卡 | TTL > CP 预期 downtime |
| **CP 单点** | 你 CP 挂全部客户挂 | HA 从一开始就要做 |
| **DP 强依赖 CP 在线** | CP 1 小时挂 → DP 业务全停 | DP 必须能用 stale cache 继续跑 |
| **Config schema 频繁改** | CP 改了 schema 老 DP 不认 | Config schema 版本化 + 向后兼容 |
| **DP 内部状态依赖 CP** | DP restart 后丢上下文 | DP 状态自包含 + CP 只下发 config |
| **多客户 CP database 跨租户读漏** | 客户 A 拿到客户 B 的 config | Row-level security + customer_id 必须在所有 query |
| **CP API key 泄漏** | 一个客户的 DP 能拉别客户 config | API key 加 scope，CP 验证 |

### 8.2 运维坑

| 坑 | 解释 | 防止 |
|---|---|---|
| **CP 部署中 DP 拉 config 失败** | 滚动升级时短暂 502 | Blue-green CP + DP 优雅降级 |
| **DP 版本太老不支持新 CP API** | 你 ship 新 API，老 DP break | API 版本号 + 老版本支持期 |
| **客户 deployment 之间 CP 实验串了** | A/B test 把客户 A 当 B | 实验 flag 必须 customer-scoped |
| **Telemetry 太啰嗦 CP 撑不住** | DP 每秒 push → CP 倒下 | 必须 batch + rate limit |
| **Telemetry 漏数据反而看不到问题** | DP 挂了不 push，CP 以为没事 | "心跳"机制，N 秒没消息算挂 |
| **Telemetry 偷偷带了 PII** | DP 上报错误时带了用户邮箱 | 强制 scrub middleware |

### 8.3 商务 / 客户感知坑

| 坑 | 解释 | 防止 |
|---|---|---|
| **客户问"CP 挂了我业务挂吗"** | 客户 fear | 文档化 stale cache 行为 + SLA |
| **客户问"你能看我数据吗"** | 客户 fear | "CP 下发 config, DP 处理数据, 我们看不到原文" + 合同 |
| **客户问"我用客户 A 的 config 试试"** | tenant isolation 信任问题 | 解释 row-level security |
| **客户停服怎么办** | 数据归客户但 prompt 没了 | 合同写明 "license 终止 = DP 停" |
| **CP 升级需要 DP 配合升级** | 你想 ship 但客户不动 | 双向兼容 + 强制升级时间表 |
| **客户 IT 看 DP 觉得"什么都没做"** | "你们卖的就这个？" | UI / marketing 强调 CP 价值 |

### 8.4 跨边界 debug 坑

| 坑 | 解释 | 防止 |
|---|---|---|
| **trace_id 没串通 CP 和 DP** | bug 只看一边看不出 | OpenTelemetry，trace_id 跨边界传 |
| **DP error 上报 stack 含路径** | leak 客户 cloud 内部结构 | Scrub |
| **CP 看到客户 token 上的用户名** | 你不该看见的数据 | Token 用 hash 不用 email |
| **Logs 不结构化** | grep 多客户日志查不到 | Structured logging from day 1 |

---

## 9. 法律 / 合规含义

模式 4 比模式 3 更复杂，DPA 要加：

- **Sub-processor list 加你 CP**：客户数据虽然不出客户云，但 config 来自你，你得算 sub-processor
- **CP 数据保留**：你 telemetry 保留多久、客户数据是否真的不进 CP（要写明）
- **CP 在哪个 region**：客户可能要求 CP 也在他们 region（影响你 SaaS 部署）
- **CP downtime 谁负责**：SLA 必须包含 CP 部分
- **License 终止流程**：客户不续费 → DP 停 → 但客户数据归客户

---

## 10. 决策清单：要不要走模式 4？

回答这些问题，3 个或以上 "是" 就该开始 Phase 1：

- [ ] 我有 ≥ 5 个客户在用模式 3？
- [ ] 我的 prompts 是真正的差异化 IP（竞争对手能直接抄）？
- [ ] 客户 IT 已经**明确**抱怨能看到我代码？
- [ ] 我想要"持续优化 prompts 不需要重新部署"的能力？
- [ ] 我有资源（工程时间 + 钱）维护一个 SaaS CP（包括 HA、oncall、监控）？
- [ ] 我的下一轮融资 / 销售 pitch 需要"hybrid architecture" 这个故事？

如果没到 3 个"是"——**留在模式 3**。模式 4 是 power tool，错误使用伤害自己。

---

## 11. 关键参考

- 模式 3（BYOC 基础）：见 `deployment-mode-3-byoc.md`
- 当前 stack 架构：见 `CLAUDE.md` (CEO_platform_v2)
- Phase A/B 改动详情：见 `~/.claude/plans/phase-code-azure-phase-a-purring-pumpkin.md`

---

## 附录 A：CP/DP 通信协议草稿

如果你将来要走 Phase 1，这是最简单的协议：

```
GET  /api/v1/skills/{skill_id}
GET  /api/v1/skills/{skill_id}?version=20260605-v1
GET  /api/v1/sections/{section_id}
GET  /api/v1/orchestration/{module_id}
POST /api/v1/metrics
POST /api/v1/errors
GET  /api/v1/license/verify
```

Auth: Bearer token (per-customer)
Format: JSON
Versioning: API path 含 `/v1/`

## 附录 B：DP 启动顺序

```
1. Read env: CP_URL, CP_API_KEY, CUSTOMER_ID, DATA_DIR
2. Verify license: GET /api/v1/license/verify
   - 失败 → fatal exit
3. Bootstrap config:
   - 尝试拉所有 skills (parallel)
   - 失败但 cache 存在 → 用 cache，警告
   - 失败 + 无 cache → fatal exit
4. Start FastAPI, Scheduler, etc.
5. Start telemetry heartbeat (每 30s)
```

## 附录 C：CP 启动顺序

```
1. Read env: DATABASE_URL, SIGNING_KEY (Phase 5), etc.
2. Verify DB schema (migrate if needed)
3. Start FastAPI
4. Start customer dashboard
5. Start telemetry aggregator
6. Start alerting (Sentry / PagerDuty)
```
