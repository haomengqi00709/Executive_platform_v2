IS_ACTION = True


def build(ctx):
    def forward_file(to: str, subject: str = "", note: str = "") -> str:
        """Attach the most recently received file to a NEW Outlook draft addressed to `to`. Drafts only."""
        pf = ctx.state.get("pending_file")
        if not pf or not pf.get("onedrive_path"):
            return ("There's no file to forward right now — ask the user to send me the file first, "
                    "then tell me who to forward it to.")

        # A draft needs a real address — resolve a bare name to the contact's (grouped) primary email.
        recipient = (to or "").strip()
        if recipient and "@" not in recipient:
            try:
                from src.modules.crm import find_contacts_by_name
                hits = find_contacts_by_name(ctx.data_dir, recipient)
                if len(hits) == 1:
                    recipient = hits[0].get("email") or (hits[0].get("emails") or [""])[0] or recipient
                elif len(hits) > 1:
                    names = ", ".join(f"{h.get('name')} <{h.get('email') or (h.get('emails') or [''])[0]}>"
                                      for h in hits[:5])
                    return f"Which one did you mean? I found: {names}. Give me the exact email."
                else:
                    return f"I couldn't find a contact named '{to}'. Give me their email address."
            except Exception:
                return f"Give me {to}'s email address so I can attach the file to a draft."
        if "@" not in recipient:
            return "I need a valid email address to attach the file to a draft."

        g = ctx.owner_graph or ctx.graph
        try:
            from urllib.parse import quote
            encoded = quote(pf["onedrive_path"], safe="/")
            content = g.download(f"/me/drive/root:/{encoded}:/content")
        except Exception as e:
            return f"I couldn't retrieve the saved file to attach it: {e}"

        try:
            filename = pf.get("filename") or "document"
            subj = subject or f"Forwarding: {filename}"
            body = note or f"Hi,\n\nPlease find attached {filename}.\n\nThanks."
            draft = g.create_draft(subject=subj, body=body, to=recipient)
            g.add_file_attachment(draft.get("id"), filename, content, pf.get("mime"))
            ctx.state["pending_file"] = None
            link = draft.get("webLink") or ""
            return (f"📎 Draft to {recipient} created with '{filename}' attached — saved to your Drafts. "
                    f"Review and send it when you're ready." + (f"\n{link}" if link else ""))
        except Exception as e:
            return f"I couldn't create the draft with the attachment: {e}"
    return forward_file
