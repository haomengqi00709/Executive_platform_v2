from datetime import datetime, timedelta

IS_ACTION = True

_WD = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _resolve_date(day_word: str, now: datetime):
    """Resolve a relative/absolute day to a date using the user-local `now`.

    Date is computed in CODE, never by the AI — so stale dates in conversation history
    (the 'today is June 20' history-poisoning bug) can't push the event onto the wrong day.
    Accepts: '' / 'today', 'tomorrow', weekday names ('friday', 'next friday'),
    or an absolute 'YYYY-MM-DD'. Falls back to today on anything unparseable.
    """
    raw = (day_word or "").strip().lower()
    d = raw.replace("this ", "").replace("next ", "").strip()
    base = now.date()
    if d in ("", "today"):
        return base
    if d in ("tomorrow", "tmr"):
        return base + timedelta(days=1)
    if d in _WD:
        delta = (_WD.index(d) - base.weekday()) % 7
        if delta == 0 and "next" in raw:
            delta = 7
        return base + timedelta(days=delta)
    try:
        return datetime.fromisoformat((day_word or "").strip()[:10]).date()
    except Exception:
        return base


def build(ctx):
    def create_calendar_event(subject: str, start_iso: str = "", day: str = "",
                              end_iso: str = "", attendee_emails: str = "",
                              location: str = "", is_online_meeting: bool = True) -> str:
        from src.modules.tz import get_user_tz
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            tz = get_user_tz(ctx.data_dir)
            now = datetime.now(tz)

            # The TIME comes from the AI's start_iso (models are reliable at time-of-day);
            # the DATE is resolved in code from `day` + user-local `now`, so it can't be
            # corrupted by stale dates in the conversation history.
            def _hm(s):
                try:
                    dt = datetime.fromisoformat(s)
                    return dt.hour, dt.minute
                except Exception:
                    return None

            hm = _hm(start_iso) or (9, 0)
            if (day or "").strip():
                d = _resolve_date(day, now)
                start_dt = now.replace(year=d.year, month=d.month, day=d.day,
                                       hour=hm[0], minute=hm[1], second=0, microsecond=0)
            elif (start_iso or "").strip():
                try:
                    start_dt = datetime.fromisoformat(start_iso)
                except Exception:
                    return "⚠️ Need a valid start time — what day and time should it start?"
                # Past-date guard: a date in the past is almost always the stale-history bug,
                # not the user's intent — re-anchor to today, keep the time.
                if start_dt.date() < now.date():
                    start_dt = start_dt.replace(year=now.year, month=now.month, day=now.day)
            else:
                return "⚠️ What day and time should it start?"

            start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            if not (end_iso or "").strip():
                end_iso = (start_dt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")

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
            web_link = result.get("webLink", "")
            join_url = (result.get("onlineMeeting") or {}).get("joinUrl", "")
            msg = f"✅ Event created: '{subject}' from {start_iso} to {end_iso}"
            if attendees:
                msg += f" · Invites sent to: {', '.join(attendees)}"
            if join_url:
                msg += f"\n🔗 Teams link: {join_url}"
                ctx.state["_last_event_join_url"] = join_url
            if web_link:
                ctx.state["_last_event_web_link"] = web_link
            return msg
        except Exception as e:
            return f"Error creating event: {e}"
    return create_calendar_event
