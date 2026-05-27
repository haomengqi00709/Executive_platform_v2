"""
AADSTS error code → user-friendly English message + recommended action.

Two layers:
  1. HARDCODED map — top refresh-token failure modes, hand-written messages
  2. AI fallback for unknown codes, results cached to .data/.aadsts_cache.json
     so we don't re-translate the same code twice.

Action types:
  re-login       — user fixes by re-signing-in the affected account
  contact-admin  — tenant-level issue, IT admin must act
  unknown        — AI couldn't classify; treat as re-login + show raw error
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent / ".data")))
CACHE_FILE = DATA_DIR / ".aadsts_cache.json"


HARDCODED: dict[int, dict] = {
    50173: {
        "message": "Your Microsoft password was recently changed, so the saved sign-in is no longer valid.",
        "action": "re-login",
    },
    70008: {
        "message": "The sign-in session expired because the account was inactive for too long.",
        "action": "re-login",
    },
    700082: {
        "message": "The sign-in token expired and needs to be renewed.",
        "action": "re-login",
    },
    50076: {
        "message": "Microsoft now requires multi-factor authentication for this account. Please sign in again to complete it.",
        "action": "re-login",
    },
    50079: {
        "message": "Your IT admin enabled multi-factor authentication on this account. Please sign in again and set it up.",
        "action": "re-login",
    },
    65001: {
        "message": "An admin revoked the application's permission to access this Microsoft account. IT must re-grant consent before sign-in will work.",
        "action": "contact-admin",
    },
    500011: {
        "message": "The application is disabled in your Microsoft organization. IT must re-enable it before sign-in will work.",
        "action": "contact-admin",
    },
    530003: {
        "message": "Your company's security policy blocked this sign-in (e.g. the device is not compliant or the network is not allowed). Contact IT.",
        "action": "contact-admin",
    },
    50034: {
        "message": "The Microsoft account no longer exists. Contact IT to restore or recreate it.",
        "action": "contact-admin",
    },
    50057: {
        "message": "The Microsoft account is disabled. Contact IT to re-enable it.",
        "action": "contact-admin",
    },
}


_AI_PROMPT = """You are mapping a Microsoft Entra (Azure AD) sign-in error to a brief,
user-friendly English explanation. The user is a business executive, NOT technical.

Microsoft error code: AADSTS{code}
Microsoft technical description: {description}

Reply in this exact JSON format (no markdown, no preamble):
{{"message": "<one sentence, plain English, no jargon, says what happened>",
  "action": "<one of: re-login, contact-admin>"}}

Choose "re-login" if the user can fix this themselves by signing in again.
Choose "contact-admin" if it requires a tenant administrator (consent, app config,
account disable/delete, conditional access, security policy, etc.).
"""


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _ai_classify(code: int, description: str) -> dict | None:
    try:
        from src.ai import AIClient
        ai = AIClient()
        raw = ai.generate(_AI_PROMPT.format(code=code, description=description or "(none)"))
        m = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group(0))
        if "message" not in parsed or parsed.get("action") not in ("re-login", "contact-admin"):
            return None
        return {"message": parsed["message"].strip(), "action": parsed["action"]}
    except Exception as e:
        print(f"[auth_errors] AI classify failed for AADSTS{code}: {e}")
        return None


def classify_aadsts(error_code: int | None, error_description: str = "") -> dict:
    """Returns {code, message, action, source}.

    source ∈ {"hardcoded", "ai", "fallback"}.
    Always returns a usable result — never raises.
    """
    if error_code is None:
        return {
            "code": None,
            "message": "Could not sign in to Microsoft (no error code returned). Please try signing in again.",
            "action": "re-login",
            "source": "fallback",
        }

    if error_code in HARDCODED:
        h = HARDCODED[error_code]
        return {"code": error_code, "message": h["message"], "action": h["action"], "source": "hardcoded"}

    cache = _load_cache()
    key = str(error_code)
    if key in cache:
        c = cache[key]
        return {"code": error_code, "message": c["message"], "action": c["action"], "source": "ai"}

    ai_result = _ai_classify(error_code, error_description)
    if ai_result:
        cache[key] = {
            **ai_result,
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "description_seen": error_description[:300],
        }
        _save_cache(cache)
        return {"code": error_code, **ai_result, "source": "ai"}

    return {
        "code": error_code,
        "message": f"Microsoft sign-in failed (error AADSTS{error_code}). Please try signing in again, or contact your IT admin if it keeps failing.",
        "action": "re-login",
        "source": "fallback",
    }


def extract_aadsts_code(msal_result: dict | None) -> tuple[int | None, str]:
    """Pull AADSTS code + description out of an MSAL error response dict.

    MSAL returns errors as {error, error_description, error_codes, correlation_id, ...}.
    error_codes is a list of ints. error_description is human-readable, also contains
    'AADSTS<code>:' prefix.
    """
    if not msal_result:
        return None, ""
    codes = msal_result.get("error_codes") or []
    code = codes[0] if codes else None
    description = (msal_result.get("error_description") or "").strip()

    if code is None and description:
        m = re.search(r"AADSTS(\d+)", description)
        if m:
            code = int(m.group(1))

    return code, description
