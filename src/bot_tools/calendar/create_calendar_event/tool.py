from datetime import datetime, timedelta

IS_ACTION = True


def build(ctx):
    def create_calendar_event(subject: str, start_iso: str, end_iso: str = "",
                              attendee_emails: str = "",
                              location: str = "",
                              is_online_meeting: bool = False) -> str:
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            if not (end_iso or "").strip():
                try:
                    end_iso = (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()
                except Exception:
                    return "⚠️ Need a valid start time to schedule this — what time should it start?"
            attendees = [a.strip() for a in attendee_emails.split(",") if a.strip()] if attendee_emails else []
            result = owner_graph.create_event(
                subject=subject,
                start=start_iso,
                end=end_iso,
                attendees=attendees or None,
                location=location or None,
                timezone=ctx.settings.get("timezone", "UTC"),
                is_online=is_online_meeting,
            )
            event_id = result.get("id", "")
            web_link = result.get("webLink", "")
            msg = f"✅ Event created: '{subject}' from {start_iso} to {end_iso}"
            if attendees:
                msg += f" · Invites sent to: {', '.join(attendees)}"
            if web_link:
                ctx.state["_last_draft_web_link"] = web_link
            return msg
        except Exception as e:
            return f"Error creating event: {e}"
    return create_calendar_event
