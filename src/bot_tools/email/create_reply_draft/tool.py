import json

IS_ACTION = True


def build(ctx):
    def create_reply_draft(to: str, subject: str, body: str) -> str:
        ctx.state["pending_draft"] = {"to": to, "subject": subject, "body": body}
        print(f"[Bot] create_reply_draft staged → '{subject}' to {to}")
        return json.dumps({
            "staged": True, "to": to, "subject": subject, "body": body,
            "next": "Show the user this draft (To, Subject, Body verbatim). Then ask them to "
                    "reply '1' or 'save' to save it to Outlook Drafts, or tell you what to change.",
        }, ensure_ascii=False)
    return create_reply_draft
