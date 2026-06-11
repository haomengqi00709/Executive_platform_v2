# Security & Deployment — 每项具体清单

> 每个 tier 的每个 security 项目，逐条说清楚：是什么、为啥客户在意、我们现在怎样、要做什么。

---

# Tier A: SaaS（我们 host）

## A.1 Encryption at rest + in transit
- **是什么**：数据存储时加密 + 网络传输 HTTPS/TLS
- **客户为啥在意**：备份磁盘被偷或网络中间人窃听时数据不可读
- **现状**：✅ Railway 默认 TLS 1.3 + AES-256 at rest
- **要做的**：
  - 在 Privacy Policy 里写明 "TLS 1.3 in transit, AES-256 at rest"
  - 客户问起来用同一句话回答
- **工程量**：0（已有）

## A.2 Account isolation
- **是什么**：用户 A 不能访问 / 影响用户 B 的数据
- **客户为啥在意**：跨账号数据泄漏是 SaaS 最大风险
- **现状**：✅ `.data/{user_id}/` 物理隔离，每个 API 从 session 拿 user_id
- **要做的**：
  - 写 2-3 个测试验证隔离：
    - 用户 B 登录后调一个 API 传 user_id=A → 必须 401/403 或忽略 user_id 参数
    - 文件操作必须用 `data_dir = .data/{session_user_id}/`，绝不用 query 参数的 user_id
  - 全 codebase grep `user_id` 看有没有从 request body / query 取的（应该都从 session）
- **工程量**：半天 audit + 1-2 个 test

## A.3 Microsoft OAuth 登录
- **是什么**：用 Microsoft 账号登录，不存任何密码
- **客户为啥在意**：密码泄漏风险 / SSO 政策合规
- **现状**：✅ 已用 MSAL Authorization Code Flow
- **要做的**：无
- **工程量**：0

## A.4 删账号 UI 按钮
- **是什么**：客户在 Settings 页面点一下，所有数据 + OAuth 撤销
- **客户为啥在意**：GDPR right to erasure / 信任 / 控制感
- **现状**：❌ 后端能 `rm -rf` 但没 endpoint，也没 UI
- **要做的**：
  ```python
  # src/server.py
  @app.delete("/api/account")
  def delete_account(session: dict = Depends(require_session)):
      uid = session["user_id"]
      import shutil
      shutil.rmtree(auth.DATA_DIR / uid, ignore_errors=True)
      (auth.DATA_DIR / "_sessions" / f"{uid}.json").unlink(missing_ok=True)
      # TODO: 调 https://login.microsoftonline.com/common/oauth2/v2.0/logout 撤销 consent
      resp = JSONResponse({"deleted": True})
      resp.delete_cookie("session_token")
      return resp
  ```
  - 前端 Settings 页加按钮 + 二次确认 modal（"你确定？所有数据将永久删除"）
- **工程量**：1 天

## A.5 Privacy Policy 页面
- **是什么**：1-2 页对外文档，解释你怎么处理数据
- **客户为啥在意**：GDPR / CCPA 法律要求 + 信任
- **现状**：❌ 没有
- **要做的**：
  - 用 TermsFeed / Termly 生成模板（免费），填入你的具体内容：
    - 我们收集什么：Microsoft 365 邮件、日历、OneDrive 文件、Teams 对话
    - 用来做什么：5 个 AI 模块（早报 / 邮件分类 / 会议转录 / 关系 / 费用）
    - 怎么存储：TLS in-transit, AES-256 at-rest, Railway (US-east)
    - Sub-processor：Microsoft Graph、Google Gemini
    - 客户权利：访问、导出、删除
    - 联系方式：你的 email
  - 加到 frontend `/privacy` 路由
  - **Beta 阶段不用律师审**
- **工程量**：2-3 小时

## A.6 Sub-processor list
- **是什么**：1 页列出所有 share 客户数据的第三方
- **客户为啥在意**：透明度 / GDPR 法律要求
- **现状**：❌ 没公开
- **要做的**：
  - 加 frontend `/subprocessors`，内容：

    | Sub-processor | 用途 | 处理什么 | 位置 |
    |---|---|---|---|
    | Microsoft Graph API | OAuth + 数据访问 | 邮件 / 日历 / 文件 metadata | Microsoft cloud |
    | Google Gemini API | AI 文本/语音/视频处理 | 邮件正文 / 转录 (in-transit only) | Google cloud |
    | Railway | 基础设施 hosting (Tier A only) | All user data at rest | Railway US-east |
- **工程量**：1 小时

## A.7 数据 residency 告知
- **是什么**：明确告诉客户数据物理在哪个国家/region
- **客户为啥在意**：GDPR 数据主权 / 加拿大 / 中国客户特别在意
- **现状**：❌ Railway 在哪 region 你确认下，没告诉客户
- **要做的**：
  - Railway dashboard 确认 region（你账户 Settings → Region）
  - 写进 Privacy Policy + onboarding 首屏
- **工程量**：30 分钟

## A.8 备份策略
- **是什么**：定期 snapshot 数据，灾难时能恢复
- **客户为啥在意**：你 ransomware / Railway 挂时他不丢数据
- **现状**：⚠️ Railway 默认 PG backup 有，volume 你确认下
- **要做的**：
  - Railway dashboard 验证：
    - PostgreSQL: 默认 daily backup（确认开着 + 看保留天数）
    - Volume：Railway 目前不自动 snapshot volume，需要你手动
  - 写一份 "Backup & Restore SOP"（即使是手动也得有文档）
  - 推荐：每周自己 `tar -czf` 一次 `.data/` push 到你 S3 / Backblaze
- **工程量**：1-2 小时

## A.9 Incident notification 流程
- **是什么**：出 breach / 大 outage 时怎么通知客户
- **客户为啥在意**：GDPR 要求 72h 内通知 / 信任
- **现状**：❌ 没文档
- **要做的**：
  - 写一份 1 页 Incident Response Plan：
    1. **发现**：监控告警 / 客户报告
    2. **评估**：影响范围 / 数据有没有泄漏
    3. **通知**：72h 内邮件给所有受影响客户
    4. **修复**：临时 mitigation + 长期 fix
    5. **总结**：post-mortem，发给客户
  - 配 UptimeRobot 免费版（每 5 分钟 ping 你的 URL，挂了发邮件给你）
- **工程量**：2-3 小时

## A.10 Vendor 访问 audit log
- **是什么**：记录你 (vendor) 何时访问了哪个客户数据
- **客户为啥在意**：监督你不要乱看 / 出事追责
- **现状**：❌ 没自己的 audit log
- **要做的（beta 阶段可以跳过）**：
  - 后端 middleware 记录所有 admin endpoint 调用
  - 存到独立 `audit_log` 表
  - 每月给客户邮件：本月 vendor 访问 X 次（detail link）
- **工程量**：1 天
- **建议**：Beta 阶段 skip，5+ 客户时做

## A.11 SOC2
- **是什么**：第三方审计认证
- **客户为啥在意**：大企业必要
- **现状**：❌ 没
- **要做的**：现在 skip。5+ 客户 + 有 enterprise lead 才考虑
- **工程量**：几个月 + $20-50k

---

# Tier B: BYOC（客户 Azure）

## B.1 数据完全在客户 cloud
- **是什么**：所有客户邮件 / 会议 / 文件存在客户 Azure Files
- **客户为啥在意**：数据主权
- **现状**：✅ `/mnt/data` 挂客户 Azure Files
- **要做的**：
  - **必须 verify**：grep 全 codebase 看有没有写到非 `DATA_DIR` 路径的代码（不能有偷偷写 `/tmp` 持久化、`/var` 等的情况）
- **工程量**：半天 audit

## B.2 客户拥有 subscription
- **是什么**：Azure 账单是客户的，他能随时停服
- **客户为啥在意**：控制权
- **现状**：✅ IPS 案例如此
- **要做的**：
  - Onboarding 文档明确写"客户必须自己开 Azure subscription，付 Azure 账单"
- **工程量**：30 分钟文档

## B.3 客户能撤销 vendor 访问
- **是什么**：客户在 Azure Portal 删除你 service principal，你立刻失去访问
- **客户为啥在意**：紧急情况能立刻断开
- **现状**：✅ Azure 原生
- **要做的**：
  - 给客户的 handover 文档加一段："如何撤销 vendor 访问"：
    1. Azure Portal → Subscriptions → Access control (IAM)
    2. 找到 vendor 的 service principal
    3. Remove
- **工程量**：30 分钟文档

## B.4 Encryption (BYOC)
- **是什么**：at rest + in transit
- **客户为啥在意**：标准
- **现状**：✅ Azure Storage SSE 默认 + App Service HTTPS 默认
- **要做的**：无
- **工程量**：0

## B.5 客户能审计
- **是什么**：客户看 Azure Activity Log 知道你做了啥
- **客户为啥在意**：监督 vendor
- **现状**：✅ Azure 自动记录
- **要做的**：
  - Handover 文档告诉客户去哪看：Azure Portal → Activity log
  - 解释什么操作会出现 entry
- **工程量**：30 分钟文档

## B.6 Vendor 访问最小权限
- **是什么**：你只有最低必要 RBAC role
- **客户为啥在意**：principle of least privilege / 减少 vendor 误删风险
- **现状**：⚠️ 你目前 IPS 给的 role 范围（你确认下，理想是 RG 级 Contributor，不是 subscription 级 Owner）
- **要做的**：
  - 当前 IPS：确认 role 是 resource group `ceo-platform` 的 Contributor，不是 subscription 的 Owner
  - 未来新客户：默认要求客户给 RG-scoped Contributor
  - 进阶：定义 Custom Role 只允许 `Microsoft.Web/sites/*/read` + `Microsoft.Web/sites/restart` + image swap，**不允许**读 Storage（这样你连数据都看不到）
- **工程量**：1 小时（per customer）

## B.7 MSA + NDA + IP Assignment
- **是什么**：法律合同
- **客户为啥在意**：商务必备
- **现状**：❌ 没
- **要做的**：
  - 找懂软件/SaaS 的商业律师
  - 起草 3 份文档：
    - **MSA** (Master Services Agreement)：服务范围、SLA、付款、终止、责任限制
    - **Mutual NDA**：双向保密
    - **IP Assignment**：代码 IP 归你、客户数据归客户、客户不得 reverse engineer / 复制 / 转售
  - 模板化，第 2 客户起改名字就能用
- **工程量**：律师 2-3 周，~$3-5k 一次性。**你这边 0 工程**

## B.8 DPA (Data Processing Agreement)
- **是什么**：法律文件，客户授权你处理他数据
- **客户为啥在意**：GDPR / PIPEDA 必备
- **现状**：❌ 没
- **要做的**：
  - 跟 MSA 一起让律师起草
  - 内容：
    - 处理目的（5 个模块各自）
    - Sub-processor 清单（Microsoft、Google）
    - 安全措施（加密、isolation）
    - 通知义务（breach 72h）
    - 客户离开后 deletion timeline
  - 当 EU / 加拿大客户必须有，否则违法
- **工程量**：律师做

## B.9 Sub-processor list (BYOC)
- **同 A.6**，但额外列：
  - 客户自己 Azure（hosting）
  - 不算"sub-processor"——是客户自己 infra

## B.10 Vendor 访问通知 / 流程
- **是什么**：vendor 进客户云之前的通知协议
- **客户为啥在意**：监督
- **现状**：❌ 没
- **要做的**：
  - 写进 SLA：
    > "Vendor 因 debug 需要访问客户 Azure 时，将提前 24h 邮件通知客户，紧急情况事后 24h 内告知。"
  - 实操：你 debug 前发一封邮件给客户的 main contact
- **工程量**：1 小时文档 + 流程

## B.11 客户离开 deletion checklist
- **是什么**：客户取消时怎么删数据
- **客户为啥在意**：法律 + 信任
- **现状**：❌ 没
- **要做的**：
  - Checklist 文档：
    1. 客户在 Azure Portal 删除 Resource Group → storage + image + app 全没
    2. 你从 ACR 删除该客户专属 image tags
    3. 你撤销 service principal 自身的 access key
    4. 删 GitHub Actions 的客户 secrets
    5. 撤销 OAuth tokens（让客户在 https://myaccount.microsoft.com → Permissions 撤销）
    6. 邮件确认给客户："已删除以下资源 [list]，时间 [date]"
  - 给客户 deletion certificate 模板
- **工程量**：1-2 小时文档

## B.12 Diagnostic bundle endpoint
- **是什么**：客户报 bug 时生成一份 scrubbed 诊断包，客户自己下载发你
- **客户为啥在意**：你不进客户云就能 debug = 客户安心
- **现状**：❌ 没
- **要做的**：
  ```python
  @app.get("/admin/diagnostic_bundle")
  def diagnostic_bundle(token: str):
      expected = os.getenv("DIAG_TOKEN") or ""
      if not expected or not secrets.compare_digest(token, expected):
          raise HTTPException(403)
      bundle = {
          "version": os.getenv("APP_VERSION", "unknown"),
          "uptime_secs": int(time.time() - START_TIME),
          "env_redacted": {
              k: "<set>" if v else "<empty>"
              for k, v in os.environ.items()
              if "SECRET" in k or "KEY" in k or "TOKEN" in k
          },
          "module_health": run_health_checks(),
          "recent_errors": tail_log_scrubbed(lines=200),
          "users_count": len(list((auth.DATA_DIR / "_sessions").glob("*.json"))),
      }
      return Response(zip_bytes(bundle), media_type="application/zip")
  ```
  - 你给客户临时 DIAG_TOKEN，他们 `curl` 下载
  - 每个客户 token 唯一，过期失效
- **工程量**：半天

## B.13 Customer onboarding runbook
- **是什么**：部署新客户的 step-by-step
- **客户为啥在意**：客户不直接要，但你和 partner 需要
- **现状**：🟡 草稿在 `docs/deployment-mode-3-byoc.md` §5.1
- **要做的**：
  - 根据 IPS 部署经验更新 runbook
  - 每步加：
    - 你做什么
    - 客户做什么
    - 怎么 verify
    - 出问题怎么办
- **工程量**：半天

---

# Tier C: Hybrid (CP/DP)

详见 `docs/deployment-mode-4-control-data-plane.md`。

简要说：**6 个月内不做**。需要先有 5+ BYOC 客户 + 至少 1 个客户明确要求 prompt 不可见。

---

# 跨 Tier 通用 gaps

## X.1 Logs PII scrubbing
- **是什么**：日志自动把邮件 / 姓名替换成 `<email>` / `<name>`
- **客户为啥在意**：防止 logs 落入 Sentry / Azure log analytics 时 PII 外漏
- **现状**：❌ 没
- **要做的**：
  ```python
  # src/main.py 或 logging setup
  import logging, re
  
  class PIIFilter(logging.Filter):
      EMAIL_RE = re.compile(r'[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}')
      def filter(self, record):
          record.msg = self.EMAIL_RE.sub('<email>', str(record.msg))
          return True
  
  logging.getLogger().addFilter(PIIFilter())
  ```
  - 单元测试：log 一行含 `jason@gmail.com` → 输出含 `<email>` 不含 `jason@`
- **工程量**：半天

## X.2 Backup 验证
- **是什么**：不只有 backup，定期验证能 restore
- **客户为啥在意**：很多公司 backup 跑了 1 年才发现 restore 不来
- **现状**：❌
- **要做的**：
  - Tier A: 每月一次拉 Railway PG snapshot → 起测试 instance → 验证数据完整
  - Tier B: 每月给一个客户验证 Azure Files snapshot → mount → 看文件能读
  - 文档化流程（即使是手动）
- **工程量**：每次 1 小时（recurring）

## X.3 "我们用你哪些数据" 1 页（客户友好版）
- **是什么**：Privacy Policy 的简化版，给非 IT 客户看的
- **客户为啥在意**：CEO 客户不会读 5 页 Privacy Policy
- **现状**：❌
- **要做的**：
  - Frontend 加 `/about-data`：
    ```
    我们读什么：
    ✓ 你 Microsoft 365 的邮件、日历、OneDrive 文件
    ✓ 你和 Audrey bot 的对话
    
    我们用来做什么：
    ✓ 5 个 AI 模块帮你处理日常工作
    
    数据存哪：
    ✓ [SaaS]: 我们 Railway (US-east)
    ✓ [BYOC]: 你自己 Azure
    
    我们调谁：
    ✓ Microsoft Graph (经你 OAuth 授权)
    ✓ Google Gemini (AI 处理，不存)
    
    你能做什么：
    ✓ Settings 里点 "删除我所有数据"
    ✓ 撤销 Microsoft OAuth 授权
    ✓ Email 我们要求审计
    ```
  - Sign-in 流程加链接到这页
- **工程量**：1 小时

## X.4 Customer security dashboard
- **是什么**：客户能自己看自己 deployment 的 security status
- **客户为啥在意**：透明度比任何 PR 都好
- **现状**：❌
- **要做的（5+ 客户时考虑）**：
  - Frontend `/security`：
    - ✅ Encryption at rest: enabled (Azure SSE / Railway)
    - ✅ Encryption in transit: TLS 1.3
    - ✅ Vendor accessed your data: 0 times this month
    - 📋 Sub-processors: [link]
    - 🔗 Privacy Policy / DPA: [link]
- **工程量**：1 天

---

# 优先级总结

## 立刻做（这周，0-1 天工程）
- A.5 Privacy Policy（2-3 小时）
- A.6 Sub-processor list（1 小时）
- A.7 Data residency 文档（30 分钟）
- A.9 Incident response plan（2-3 小时）
- X.3 "我们用你哪些数据" 1 页（1 小时）
- B.2/B.3/B.5/B.10/B.11 各种 BYOC handover 文档（合计 3-4 小时）

**总计 1-2 天，全是文档。**

## 这周-下周（轻工程）
- A.2 Account isolation audit + tests（半天）
- A.4 删账号按钮（1 天）
- A.8 Backup 验证流程（1-2 小时）
- B.1 数据路径 audit（半天）
- B.6 RBAC 缩到 RG 级（1 小时）
- B.12 Diagnostic bundle endpoint（半天）
- B.13 BYOC onboarding runbook 精修（半天）
- X.1 Logs PII scrubbing（半天）

**总计 3-4 天工程。**

## 法律（异步，最长 lead time）
- B.7 MSA + NDA + IP（律师 2-3 周，~$3-5k）
- B.8 DPA（一起做）

**今天就找律师，是 Tier B 上线的真正瓶颈。**

## Beta 阶段先 skip
- A.10 Vendor access audit log
- A.11 SOC2
- X.2 Backup 验证 recurring（手动 monthly 先）
- X.4 Customer security dashboard
- 全部 Tier C
