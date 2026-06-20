IS_ACTION = True


def build(ctx):
    def draft_group_email(group: str, message: str, context_note: str = "") -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import resolve_group
            res = resolve_group(data_dir, group)

            if res["mode"] == "none":
                groups = res["all_groups"]
                if not groups:
                    return f"You don't have any contact groups yet, so there's no group named '{group}'."
                listing = ", ".join(f"{g['tag']} ({g['count']})" for g in groups[:20])
                return f"I couldn't find a group named '{group}'. Your groups are: {listing}. Which one did you mean?"

            if res["mode"] == "substring" and len(res["candidate_tags"]) > 1:
                cands = ", ".join(f"{g['tag']} ({g['count']})" for g in res["candidate_tags"])
                return f"'{group}' matches several groups: {cands}. Which one should I draft to?"

            tag = res["matched_tag"] or res["candidate_tags"][0]["tag"]
            valid = [c for c in res["contacts"]
                     if (c.get("email") or "").strip() and "@" in (c.get("email") or "")]
            if not valid:
                return f"The group '{tag}' has no contacts with a usable email address."

            emails = [c["email"].strip() for c in valid]
            names  = [c.get("name") or c["email"] for c in valid]
            ctx.state["pending_group_email"] = {
                "tag": tag, "intent": message, "context_note": context_note,
                "emails": emails, "names": names,
            }
            shown = ", ".join(names[:10]) + (f", and {len(names) - 10} more" if len(names) > 10 else "")
            return (f"I'll draft a personalized email about '{message}' to the {len(emails)} "
                    f"people in '{tag}': {shown}. Reply 'go ahead' to create the drafts — "
                    f"they'll go to your Outlook Drafts to review, and nothing sends automatically.")
        except Exception as e:
            return f"Error preparing group email: {e}"
    return draft_group_email
