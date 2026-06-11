# 模式 3：BYOC (Bring Your Own Cloud) — 完整实操手册

> 把代码 deploy 到客户自己的 cloud subscription 里跑。
> 数据 + 代码都在客户 tenant。这是 CEO Platform v2 现在用的模式。

---

## 1. 这是什么 / 不是什么

### 是什么
- 你的代码（container image）跑在**客户的** Azure / AWS / GCP subscription 里
- 客户的数据全程不离开他们 cloud
- 你（vendor）通过客户授予的访问权限去 deploy + 运维
- 你的 IP（源码、prompts）**对客户 IT 完全可见**

### 不是什么
- ❌ 不是 SaaS（数据不在你这）
- ❌ 不是 on-prem（不是装在他们机房）
- ❌ 不是 SDK / library（你不是给他们一个 npm package）
- ❌ 不是真正"无访问"——你大概率需要持续维护，要有访问通道

### 业界叫这个的别名
- BYOC (Bring Your Own Cloud)
- VPC deployment
- Single-tenant on customer infrastructure
- Customer-hosted

---

## 2. 核心架构：谁拥有什么

| 资产 | 归属 | 谁能看 / 改 |
|---|---|---|
| Azure subscription | 客户 | 客户 IT，你（如果他们给 role） |
| Resource group / App Service / Storage | 客户 | 客户 IT，你 |
| Container image (ACR 里) | 客户的 ACR 里（你 push 进去） | 客户 IT，你 |
| 容器里的 Python 源码 | 跑在客户 infra | 客户 IT 可以 SSH 进去 `cat` |
| Prompts (`src/skills/*`) | 在 image 里 | 客户 IT 可见 |
| Env vars (含 secrets) | App Service config | 客户 IT 在 portal 看明文 |
| 客户数据 | 客户 storage | 客户拥有，你能读（如果有 role） |
| OAuth tokens | 客户 storage 里 | 同上 |
| GitHub repo（源码托管） | 你 | 只有你（除非你 invite 客户） |
| Build pipeline (GitHub Actions) | 你 | 只有你 |

**关键意义**：客户 IT 一旦想看，**全部代码都看得见**。这是 BYOC 的本质代价。

---

## 3. 五个核心运维维度

### 3.1 初始部署（Initial Deploy）

| 子模式 | 方式 | 适合 | 你现在的位置 |
|---|---|---|---|
| **A. 手动** | 你登客户 Azure，`az` 命令一行一行跑 | 1-3 客户 | ✅ 用这个（IPS 案例） |
| **B. Terraform / Bicep 模板** | 客户跑 `terraform apply` 用你的 .tf 文件 | 3-10 客户 | 第 2 客户来之前做 |
| **C. Azure Marketplace** | 客户从 Azure Portal 一键 install | 10+ 客户 | 远期目标 |

### 3.2 持续访问（Ongoing Access）

部署完不是结束。你需要持续运维、推更新、debug 客户问题。

| 模式 | 怎么做 | 业界例子 | 风险 |
|---|---|---|---|
| **No access** | deploy 完就走，问题靠客户报 ticket | GitHub Enterprise Server | support 极慢 |
| **Permanent role** | 客户给你 Contributor role 永久持有 | Databricks 早期 | 客户觉得不安全 |
| **JIT (Just-in-Time)** | 默认无权限，需要时客户临时授权 4-24h | 金融 enterprise | 响应慢 |

**你现在是 Permanent role**（IPS 给了你 Azure access）。第 2 客户来时可以给客户选项。

### 3.3 更新机制（Updates / CD）

#### 关键原则
- **每客户独立版本 pinning**——绝不让所有客户 `:latest` 跟着 main
- **每个版本永久保留**在 ACR 作为 rollback 目标
- **滚动升级**：内部 → 1 个客户 → 验证 → 其他客户

#### 当前实现（单客户）
```
push to main
   ↓
.github/workflows/azure-deploy.yml
   ↓
az acr build → tag = <timestamp>-<sha>
   ↓
az webapp config container set
```

#### 多客户怎么扩展
**方案 A — 每客户一个 workflow**（笨但简单，1-3 客户）：
```
.github/workflows/
  deploy-ips.yml      ← push to main 自动触发
  deploy-acme.yml     ← 只手动触发
```

**方案 B — 参数化 workflow**（3+ 客户推荐）：
```yaml
on:
  workflow_dispatch:
    inputs:
      customer: { type: choice, options: [ips, acme, bigco] }
      version:  { type: string, default: latest }
```
每客户一组 `AZURE_CREDENTIALS_<CUSTOMER>` secrets。

### 3.4 监控 / 日志

**核心难题**：客户 logs 在客户 cloud 里，你看不见。

| 方案 | 数据流向 | 数据主权 | 你能监控吗 |
|---|---|---|---|
| **A. 客户内部 Application Insights** | 留客户 | 完美 ✅ | ❌ 不知道客户健康度 |
| **B. Outbound telemetry** | App 主动 push 匿名 metrics 到你 SaaS | 客户合同里说清楚 | ✅ 业界标准 |
| **C. 混合** | 详细 logs 留客户，错误率 / 可用性 push | 折中 | ✅ 实际做法 |

**业界标准是 C**。你现在还是 A（只能 `az webapp log tail`），下一步加 outbound telemetry。

#### Outbound telemetry 应该发什么 / 不发什么
✅ 发：
- customer_id, version, uptime
- 模块 run count（数字）
- error rate（数字）
- 性能 metrics（latency p50/p99）

❌ 不发：
- 邮件内容、subject、sender
- 用户名、邮箱地址
- 文件名、附件
- 任何 PII

### 3.5 Support / Debug

客户报 "登录没反应" — 你看不到他们 logs，怎么 debug？

| 工具 | 怎么用 | 业界例子 |
|---|---|---|
| **Diagnostic bundle** | App 提供 `/admin/diagnostic_bundle` → 生成 scrubbed zip → 客户邮件给你 | 大部分 BYOC 公司 |
| **临时 Reader role** | 客户开 24h Reader → 你 `az login` 看 logs → 自动失效 | enterprise 标配 |
| **屏幕共享** | Zoom / Teams 看客户操作 | 小客户 demo |

**你现在阶段最该做的：加一个 diagnostic bundle endpoint**。半天工作量，解决 80% debug 问题。

---

## 4. 实践路径（按你的客户数量分阶段）

### 阶段 0：当前（IPS = 1 客户）
做的：
- ✅ env var driven config（Phase B 已修）
- ✅ GitHub Actions auto-deploy
- ✅ Azure Files 持久化
- ✅ atomic JSON writes

**该做**：
- [ ] 写一份 `docs/customer-onboarding-runbook.md`，记录这次 IPS 部署所有步骤
- [ ] 加 `/admin/diagnostic_bundle` endpoint
- [ ] 把 OAuth redirect URI list 文档化（每个客户的 URL 都得加进 Azure AD app）

### 阶段 1：第 2 客户来之前
- [ ] 把 GitHub Actions 改成参数化 workflow（一个 yml，多客户 secrets）
- [ ] 写 Terraform / Bicep 模板（让客户自己跑）
- [ ] Outbound telemetry MVP（每分钟 POST 一行到你 Railway 的 endpoint）
- [ ] 每客户独立的 `pinned_version`，禁止自动升

### 阶段 2：5 客户时
- [ ] 内部 admin dashboard（看 N 个 deployment 的健康度）
- [ ] Staged rollout（自动 canary）
- [ ] Customer-deployed Terraform（你不再需要 admin 进去）
- [ ] 标准化 customer cloud 命名（resource group naming convention）

### 阶段 3：10+ 客户
- [ ] Azure Marketplace Managed Application
- [ ] License server / activation flow
- [ ] 开始考虑模式 4 迁移（见 `deployment-mode-4-control-data-plane.md`）

---

## 5. 具体怎么做（结合你当前 stack）

### 5.1 新客户上船清单（从 IPS 推导出来的模板）

**客户侧准备（让客户做）**：
1. 开 Azure subscription（如果他们没有）
2. 创建 Resource Group: `ceo-platform-<customer>`
3. 注册 Azure AD application：
   - Name: `CEO Platform - <Customer>`
   - Supported account types: Single tenant
   - Redirect URI: `https://<webapp>.azurewebsites.net/auth/callback`
   - Create client secret，给你
4. 授予 Graph API permissions:
   - Mail.Read, Mail.ReadWrite, Mail.Send
   - Calendars.Read
   - Files.Read.All (OneDrive)
   - Chat.Read.All (Teams bot)
   - User.Read
5. Admin consent
6. 给你一个 service principal 做 Contributor on the resource group

**你侧操作**：
```bash
# 1. 创建资源
az group create -n ceo-platform-<customer> -l canadacentral

az storage account create \
  --name ceoplatform<customer>data \
  --resource-group ceo-platform-<customer> \
  --kind StorageV2 --sku Standard_LRS

az storage share create --name data --account-name ceoplatform<customer>data

az acr create \
  --name ceoplatform<customer>acr \
  --resource-group ceo-platform-<customer> \
  --sku Basic --admin-enabled true

# 2. 构建镜像
az acr build \
  --registry ceoplatform<customer>acr \
  --image ceo-platform:v1 \
  --image ceo-platform:latest \
  --platform linux/amd64 .

# 3. 创建 App Service
az appservice plan create \
  --name ceo-platform-<customer>-plan \
  --resource-group ceo-platform-<customer> \
  --is-linux --sku B1

az webapp create \
  --name ceo-platform-<customer> \
  --plan ceo-platform-<customer>-plan \
  --resource-group ceo-platform-<customer> \
  --deployment-container-image-name ceoplatform<customer>acr.azurecr.io/ceo-platform:v1

# 4. 挂 Storage
az webapp config storage-account add \
  --name ceo-platform-<customer> \
  --resource-group ceo-platform-<customer> \
  --custom-id ceodata \
  --storage-type AzureFiles \
  --share-name data \
  --account-name ceoplatform<customer>data \
  --access-key <key> \
  --mount-path /mnt/data

# 5. 配 env vars（每个客户不同）
az webapp config appsettings set \
  --name ceo-platform-<customer> \
  --resource-group ceo-platform-<customer> \
  --settings \
    PROD_CLIENT_ID=<customer's Azure AD app client ID> \
    PROD_CLIENT_SECRET=<customer's secret> \
    TENANT_ID=<customer's tenant ID> \
    SESSION_SECRET=$(python -c 'import secrets;print(secrets.token_urlsafe(32))') \
    GEMINI_API_KEY=<your Gemini key, or theirs> \
    DATA_DIR=/mnt/data \
    REDIRECT_URI=https://ceo-platform-<customer>.azurewebsites.net/auth/callback \
    FRONTEND_URL=https://ceo-platform-<customer>.azurewebsites.net \
    APP_URL=https://ceo-platform-<customer>.azurewebsites.net \
    WEBSITES_PORT=8080
```

**记得检查**：
- [ ] App Service 跑起来了（访问 URL 返回 200）
- [ ] 客户登录成功
- [ ] Onboarding 流程跑完
- [ ] Audrey bot 注册（device flow）
- [ ] m01-m05 五个模块测一遍
- [ ] CRM、Context、Settings 页面可用

### 5.2 添加 Diagnostic Bundle Endpoint

在 `src/server.py` 加：
```python
@app.get("/admin/diagnostic_bundle")
def diagnostic_bundle(token: str):
    expected = os.getenv("DIAG_TOKEN") or ""
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(403)

    bundle = {
        "version": os.getenv("APP_VERSION", "unknown"),
        "uptime_secs": time.time() - START_TIME,
        "env_redacted": {
            k: ("<set>" if v else "<empty>") if "SECRET" in k or "KEY" in k
               else v
            for k, v in os.environ.items()
        },
        "module_health": {
            "m01": _check_briefing_health(),
            "m02": _check_email_health(),
            # ...
        },
        "recent_errors": _tail_logs(lines=200, scrub_pii=True),
        "users_count": len(list((auth.DATA_DIR / "_sessions").glob("*.json"))),
    }
    return Response(
        content=zip_bytes(bundle),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=diag.zip"}
    )
```

设 `DIAG_TOKEN` env var，每次 debug 临时换一个发给客户。

### 5.3 Outbound Telemetry MVP

最简单形式：在 scheduler 加一个每分钟的 job：
```python
def _push_telemetry():
    try:
        httpx.post(
            "https://your-saas.com/api/telemetry",
            json={
                "customer_id": os.getenv("CUSTOMER_ID", "unknown"),
                "version": os.getenv("APP_VERSION"),
                "ts": datetime.utcnow().isoformat(),
                "uptime_secs": time.time() - START_TIME,
                "users_count": len(...),
                "errors_5min": _count_recent_errors(),
                # 不发任何用户数据
            },
            headers={"X-Customer-Token": os.getenv("TELEMETRY_TOKEN")},
            timeout=5,
        )
    except Exception:
        pass  # 失败不影响 app
```

你 SaaS 那边随便起个 FastAPI + Postgres 接收 → 简单 dashboard。

---

## 6. 坑（已踩过的 + 行业经验）

### 6.1 已经踩过的（CEO Platform v2 历史）

| 坑 | 怎么发生 | 防止 / 已解 |
|---|---|---|
| **Azure Files SMB JSON 写损坏** | 非原子 write 导致末尾残留字节 | atomic write（B-patch 已修） |
| **SQLite on SMB 损坏** | SQLite 文件锁在 SMB 不可靠 | WAL mode（B-patch 已修） |
| **mount path 含 `.` 被拒** | `/app/.data` 不行 | 用 `/mnt/data` |
| **Storage account kind FileStorage 不能挂** | App Service 只支持 StorageV2 | 创建时显式 `--kind StorageV2` |
| **Mac M 系列本地 build arm64** | 默认 platform 错 | 用 `az acr build` 或 `--platform linux/amd64` |
| **Sitecontainers API 冲突** | Portal 看着配了实际没生效 | 用老版 `linuxFxVersion=DOCKER\|...` |
| **Storage account 删不掉** | Auto-created backup lock | 先解锁再删 |
| **OAuth 跳错 tenant** | TENANT_ID 默认 fallback 到 IPS 值 | env 没设 = 启动失败（B-patch 已修） |
| **PROD_CLIENT_SECRET 默认 ""** | 静默挂在用户登录时 | env 没设 = 启动失败（B-patch 已修） |
| **SESSION_SECRET 默认值** | "dev-secret-change-in-prod" 写在源码 | env 没设 = 启动失败（B-patch 已修） |
| **CORS `["*"]` + credentials** | CORS 规范禁止 | 改成 FRONTEND_URL 列表（B-patch 已修） |
| **session cookie secure=False** | HTTPS 部署也允许 HTTP 传 | auto-detect REDIRECT_URI（B-patch 已修） |
| **.token_cache.json 损坏** | MSAL 全局缓存挂 → 所有 device-flow 账号挂 | 修文件 + 长期：atomic write 已加 |

### 6.2 没踩过但会遇到的

| 坑 | 危害 | 防止 |
|---|---|---|
| **每客户 deployment 代码漂移** | 给客户 A 加了一个 hack，B 升级时 break | **所有差异只能在 config，不能在代码**。把 hack 写成 feature flag。 |
| **OAuth Redirect URI 列表越来越长** | Azure AD app 同时支持 10+ 客户 URL | 第 5 客户时拆，每客户一个独立的 Azure AD app |
| **Customer IT 误删 / 改 resource** | 你不知道，发现时数据没了 | Resource lock + Azure Activity Alert |
| **`.data/` 客户自己删** | OAuth tokens、CRM 全没 | 定期 snapshot Azure Files |
| **客户没续费 Azure subscription** | App 整个 down | 合同里写"客户负责 cloud 账单" |
| **客户 tenant 改了 admin policy** | OAuth scopes 突然要求 admin consent | onboarding 时锁死哪些 permission 必须 |
| **Gemini API key 泄漏** | 你用一个 key 给所有客户，一个客户 leak 你赔死 | **每客户独立 Gemini key**，让客户付费 |
| **Container image 被反编译 / 复制** | 客户 IT pull 你 image 自用 | 合同 IP 条款 + 不要在 image 里塞惊天 secret |
| **客户问"你们删数据吗"** | 你说删了，但 ACR 里 image 还有 | 部署终止流程：客户删 RG 后你也清 ACR |
| **OAuth token 长期过期** | 用户半年没用，refresh token 失效 | 主动 detect + 邮件提醒重连（auth_notifier 已做） |
| **App Service plan 升级不平滑** | 客户升 B1→P1，container 重启数据不丢但 session 全断 | 升级前广播 + 选低峰期 |
| **Audrey bot 账号被 IT 当 dormant 删了** | 整个 Teams 推送链路挂 | 让客户 IT 把 Audrey 标记为 service account 排除 |
| **客户禁用 device flow** | Audrey bot 注册不了 | Conditional Access policy 谈判，或换 Application Permissions |
| **多客户 secrets 在 GitHub Actions 串了** | workflow 用错 customer 的 creds → deploy 到错的 cloud | 命名严格区分 + 部署前 echo customer name 确认 |
| **新 client 的 OAuth client_id 你忘了换** | 客户 A 用 B 的 client_id 登录 | 自动化检查 env vars 匹配 customer_id |

### 6.3 法律 / 商务坑

| 坑 | 怎么避 |
|---|---|
| **合同没写 IP 条款** | 客户能光明正大复用你代码。**部署前必须签 MSA + NDA + IP Assignment** |
| **没写 "no reverse engineering" 条款** | 客户能 fork 走 | 律师起草 |
| **数据所有权不清** | 客户离开时争议 | 写明"数据归客户，IP 归 vendor" |
| **GDPR / PIPEDA 谁负责** | 出事互推 | 签 DPA（Data Processing Agreement） |
| **Gemini / Microsoft 是 sub-processor** | 客户不知道数据飞过哪 | DPA 里列 sub-processor list |
| **SLA 没写清** | 客户 Azure 挂了怪你 | "我们的 SLA 不覆盖 customer cloud uptime" |
| **支持时区 / 工时** | 客户 3am 找你 | 写明 9-5 business hours |
| **价格被砍** | 客户说"反正你不 host"压价 | BYOC 应该比 SaaS **贵**（运维复杂度高） |

---

## 7. 决策框架：什么时候升模式 4？

留在模式 3 当：
- 客户 < 5 个
- 客户 IT 看你代码不构成商业威胁
- 你 prompt 库不是核心 IP（或者已经有 NDA 保护）

升级到模式 4 当：
- 客户 > 10 个，每次更新 prompt 改 N 个 deployment 痛苦
- 客户 IT **明确**抱怨能看到你代码
- 你 prompt 库变成核心 IP（"竞争对手能直接抄"）
- 想要"自动持续优化 prompts" 不重新部署

---

## 8. 决策清单（新客户来时用）

每个新客户走一次：

- [ ] **签合同**：MSA、NDA、IP Assignment、DPA
- [ ] **客户授权**：Azure subscription、tenant ID、service principal
- [ ] **隔离决策**：用客户自己 Gemini key 还是你的（**强烈建议客户付费**）
- [ ] **OAuth setup**：客户 IT 注册 Azure AD app + 给你 credentials
- [ ] **资源命名**：统一前缀 `ceo-platform-<customer>-`
- [ ] **资源创建**：Resource Group → Storage → ACR → App Service
- [ ] **代码部署**：手动（< 3 客户）或 Terraform（≥ 3）
- [ ] **挂载 Storage**：`/mnt/data`
- [ ] **配 env vars**：复制清单逐项填
- [ ] **OAuth Redirect URI**：在客户 Azure AD app 里添加新 webapp URL
- [ ] **首次登录测试**：客户主用户登录
- [ ] **Onboarding flow**：跑完所有步骤
- [ ] **Audrey bot 注册**：device flow，让客户员工把 Audrey 加成 service account
- [ ] **五模块 smoke test**：m01-m05 各跑一次
- [ ] **告诉客户 IT 怎么撤销你的 access**：写在 handover 文档里
- [ ] **配 diagnostic token**：你留备份
- [ ] **写 customer 专属 runbook**：env 值、特殊配置都记下来

---

## 9. 关键参考

- Phase A/B 改动详情：见 `~/.claude/plans/phase-code-azure-phase-a-purring-pumpkin.md`
- 部署双轨原理：见 `CLAUDE.md` "部署：Railway + Azure 双轨" 章节
- 模式 4（CP/DP 分离）：见 `deployment-mode-4-control-data-plane.md`
