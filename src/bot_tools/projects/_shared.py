"""Shared helper for the project tools — resolves a project reference against the live store,
the way the USER saw it (registry-aware). Mirrors commitments/_shared.resolve_ref."""
from src.modules import projects_store


def resolve_project_ref(ctx, data_dir, index_or_hint: str):
    """Return (project_id, name) for the referenced project.

    Order: a bare position ("2") → the 2nd item in the list the bot just showed
    (ctx.state['_shown_lists']['projects'], registered by read_module_result), else positional
    over the live visible list; then exact id; then a keyword in the project name. id/name search
    spans ALL projects (incl. ignored/archived) so "un-ignore X" can resolve."""
    s = str(index_or_hint).strip()
    if not s:
        return None, ""
    all_projects = list((projects_store.load_projects(data_dir).get("projects") or {}).values())

    if s.isdigit():
        pos = int(s)
        try:
            shown = ((((getattr(ctx, "state", None) or {}).get("_shown_lists") or {})
                      .get("projects") or {}).get("items") or [])
        except Exception:
            shown = []
        for it in shown:
            if it.get("pos") == pos and it.get("id"):
                for p in all_projects:
                    if p.get("id") == it["id"]:
                        return p["id"], p.get("name", "")
                return it["id"], (it.get("label") or it["id"])
        visible = projects_store.query_live_projects(data_dir)   # the order the user would see
        if 1 <= pos <= len(visible):
            return visible[pos - 1].get("id"), visible[pos - 1].get("name", "")
        return None, ""

    for p in all_projects:                                       # exact id
        if p.get("id") == s:
            return p["id"], p.get("name", "")

    hint = s.lower().strip()
    for p in all_projects:                                       # contiguous substring (most precise)
        if hint in (p.get("name") or "").lower():
            return p["id"], p.get("name", "")

    # Token-subset match: the model often passes a COMPRESSED name ("IPS CTO Role Alignment") that
    # isn't a contiguous substring of the full name ("IPS Consultancy — CTO Role Alignment"). Match
    # when every word of the hint appears somewhere in the name (or the kebab id). Require ≥2 hint
    # words so a single common word can't grab the wrong project.
    import re
    hint_words = [w for w in re.split(r"\W+", hint) if len(w) >= 2]
    if len(hint_words) >= 2:
        best = None
        for p in all_projects:
            hay = ((p.get("name") or "") + " " + (p.get("id") or "")).lower().replace("-", " ")
            hay_words = set(re.split(r"\W+", hay))
            if all(w in hay_words for w in hint_words):
                if best is not None:
                    return None, ""                              # ambiguous — don't guess
                best = p
        if best:
            return best["id"], best.get("name", "")
    return None, ""
