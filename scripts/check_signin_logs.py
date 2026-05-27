#!/usr/bin/env python3
"""
诊断工具：查询 Microsoft Entra (Azure AD) 的 sign-in logs，定位 token 失效原因。

为什么有这个：Railway 后端只能看到 "Could not refresh token"，
看不到 Microsoft 那一侧到底发生了什么 —— 谁登录、从哪登、用什么客户端、
是不是触发了 conditional access。这个脚本拉 Microsoft 的官方记录。

用法：
  # 查 Audrey 最近 2 小时的登录事件
  python scripts/check_signin_logs.py --upn audrey@imodel3d.com --since 2h

  # 查指定时间窗（精确定位故障时刻）
  python scripts/check_signin_logs.py --upn audrey@imodel3d.com \\
      --since 2026-05-26T17:00:00Z --until 2026-05-26T17:30:00Z

  # dump 某个事件的完整 JSON（包括 conditional access、token 协议等）
  python scripts/check_signin_logs.py --detail <event-id>

  # 换账号 / 强制重新登录
  python scripts/check_signin_logs.py --reauth

首次运行：弹出 device code，去 microsoft.com/devicelogin 输码，用 imodel3d 的
admin 账号登录授权。后续运行：自动复用 cache，不再登录。

前置条件（在 Azure portal 配一次）：
  1. App registration `ceo_platform` (client id e6e14f41-...) → API permissions
     → 加 Microsoft Graph → Delegated → AuditLog.Read.All
  2. 点 "Grant admin consent for {tenant}"
  3. 调用账号必须有 Global Reader / Reports Reader / Security Reader / Global Admin
     角色之一（在该 tenant 内）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / ".data" / ".diag_token_cache.json"

CLIENT_ID = os.getenv("DIAG_CLIENT_ID") or os.getenv("CLIENT_ID", "e6e14f41-4c7b-4c0d-b181-6710bd1c6444")
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["AuditLog.Read.All"]
GRAPH = "https://graph.microsoft.com/v1.0"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(cache.serialize())


def acquire_token(force_reauth: bool = False) -> str:
    if force_reauth and CACHE_FILE.exists():
        CACHE_FILE.unlink()

    cache = _load_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    for account in app.get_accounts():
        result = app.acquire_token_silent(SCOPES, account=account)
        if result and "access_token" in result:
            _save_cache(cache)
            print(f"[diag] Using cached token for {account['username']}", file=sys.stderr)
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit(f"Device flow init failed: {flow.get('error_description') or flow}")
    print(flow["message"], file=sys.stderr)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"Auth failed: {result.get('error_description') or result}")
    _save_cache(cache)
    username = result.get("id_token_claims", {}).get("preferred_username", "?")
    print(f"[diag] Authenticated as {username}", file=sys.stderr)
    return result["access_token"]


def parse_when(s: str) -> str:
    m = re.match(r"^(\d+)([mhd])$", s.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return s


def fetch_signins(token: str, upn: str, since: str, until: str | None, top: int) -> list:
    flt = f"userPrincipalName eq '{upn}' and createdDateTime ge {since}"
    if until:
        flt += f" and createdDateTime le {until}"
    params = {
        "$filter": flt,
        "$orderby": "createdDateTime desc",
        "$top": str(min(top, 999)),
    }
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH}/auditLogs/signIns", headers=headers, params=params, timeout=30)
    if r.status_code == 403:
        raise SystemExit(
            "403 Forbidden — 两种可能：\n"
            "  (1) app 没有 admin-consent 过 AuditLog.Read.All（去 Azure portal 加权限并 grant consent）\n"
            "  (2) 当前登录账号没有 Global/Security/Reports Reader 角色（让 tenant admin 加角色）\n"
            f"Response: {r.text[:500]}"
        )
    if r.status_code == 401:
        raise SystemExit("401 Unauthorized — token 失效，用 --reauth 重新登录")
    r.raise_for_status()
    return r.json().get("value", [])


def fetch_signin_detail(token: str, event_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH}/auditLogs/signIns/{event_id}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def format_event(idx: int, e: dict) -> str:
    ts = (e.get("createdDateTime") or "")[:19].replace("T", " ")
    app = e.get("appDisplayName") or "?"
    client = e.get("clientAppUsed") or "?"
    proto = e.get("authenticationProtocol") or ""
    ip = e.get("ipAddress") or ""
    loc = e.get("location") or {}
    geo = f"{loc.get('city') or '?'} / {loc.get('countryOrRegion') or '?'}"
    status = e.get("status") or {}
    code = status.get("errorCode", 0)
    if code == 0:
        outcome = "✓ success"
    else:
        reason = (status.get("failureReason") or "").strip()
        outcome = f"✗ {code} {reason}"[:80]
    ca_policies = e.get("appliedConditionalAccessPolicies") or []
    ca_summary = ", ".join(
        f"{p.get('displayName', '?')}={p.get('result', '?')}"
        for p in ca_policies if p.get("result") not in (None, "notApplied")
    ) or "—"
    risk = e.get("riskLevelAggregated") or "none"
    risk_state = e.get("riskState") or ""

    lines = [
        f"[{idx}] {ts} UTC   {outcome}",
        f"     App:      {app}   ({client}" + (f", {proto}" if proto else "") + ")",
        f"     From:     {ip}   ({geo})",
        f"     CA:       {ca_summary}",
        f"     Risk:     {risk}" + (f"  state={risk_state}" if risk_state else ""),
        f"     Id:       {e.get('id', '')}",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--upn", help="账号 UPN，如 audrey@imodel3d.com")
    p.add_argument("--since", default="2h", help="起点：30m / 2h / 1d 或 ISO8601 (默认 2h)")
    p.add_argument("--until", help="终点：ISO8601 或相对（可选，默认到现在）")
    p.add_argument("--top", type=int, default=50, help="最多多少条 (默认 50)")
    p.add_argument("--detail", help="dump 某个 event id 的完整 JSON")
    p.add_argument("--reauth", action="store_true", help="清掉 cache 重新登录")
    p.add_argument("--json", action="store_true", help="输出原始 JSON 而非表格")
    args = p.parse_args()

    token = acquire_token(force_reauth=args.reauth)

    if args.detail:
        print(json.dumps(fetch_signin_detail(token, args.detail), indent=2, ensure_ascii=False))
        return

    if not args.upn:
        if args.reauth:
            print("[diag] Re-auth complete.", file=sys.stderr)
            return
        p.error("--upn is required (除非用 --detail 或 --reauth)")

    since = parse_when(args.since)
    until = parse_when(args.until) if args.until else None

    events = fetch_signins(token, args.upn, since, until, args.top)

    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=False))
        return

    print(f"\nQuery: {args.upn}", file=sys.stderr)
    print(f"Since: {since}" + (f"   Until: {until}" if until else "   Until: now"), file=sys.stderr)
    print(f"Got:   {len(events)} event(s)\n", file=sys.stderr)

    if not events:
        print("(no sign-in events in this window — Microsoft logs everything,\n"
              " so empty = no actual sign-in attempts. Refresh token use is NOT\n"
              " logged here; only interactive/protocol-level sign-ins are.)",
              file=sys.stderr)
        return

    for i, e in enumerate(events, 1):
        print(format_event(i, e))
        print()

    print("Tip: 复制 Id 行的 GUID，用 --detail <id> 查完整事件（含 CA 决策、token 协议、设备指纹等）",
          file=sys.stderr)


if __name__ == "__main__":
    main()
