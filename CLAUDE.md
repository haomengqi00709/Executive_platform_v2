# CEO Platform v2

这是 CEO Platform 的重制版。v1 已验证了核心技术路径（MSAL OAuth、
Microsoft Graph API、Gemini AI、Teams 推送），但代码结构混乱、难以维护。
v2 的目标是在同样的技术栈上，构建一个干净、可扩展、可以直接部署到生产的版本。

## 工作原则

**每次修改前，必须用中文向用户说明：**
1. 准备改什么
2. 为什么这样改（不是别的方案）
3. 会影响哪些现有文件

用户确认后才动代码。

**代码标准：**
- 每个函数、模块只做一件事
- 没有临时方案（no hacks, no workarounds）
- 新功能必须考虑多用户隔离（per user_id）
- 不写注释解释"做了什么"，只在 WHY 不明显时写

**v1 已验证的关键结论（不要重新踩坑）：**
- Calendar 必须用 `get_calendar_view()`，不能用 `get_events(filter=...)`
- MSAL authority 必须用 `/common`（多租户）
- Teams Adaptive Card 不能用 `{"type":"Separator"}`，用下一个元素的 `"separator":true`
- `Action.ToggleVisibility` 在 Teams webhook 里不支持
- Draft 邮件只存 Drafts，绝不自动发送
- Railway 的 `.data/` 目录需要挂载 volume 才能持久化

## 技术栈

Python 3.13 · FastAPI · MSAL OAuth · Microsoft Graph API ·
Google Gemini · Teams Adaptive Cards · APScheduler ·
React + TypeScript + Vite + Tailwind CSS
