"""Pure text-classification helpers — no I/O, no AI.

These answer deterministic "what kind of text is this?" questions that the code
must NOT delegate to the AI (the AI is unreliable at exactly this, which is how
attendance items leaked into the overdue view in the first place).
"""
import re


# An action that is "be present at an event" — attendance, not a deliverable.
# It must START with an attendance verb (optionally after a "<Name> to " prefix
# like "Daniel to attend ...") AND name an event in the same clause.
#
# Anchoring the verb at the start protects real deliverables that merely MENTION
# a meeting ("Share the meeting recording", "Set up the tool ... onboarding call").
# The verb→noun gap consumes word tokens only — it cannot cross '.', ',', ';' or
# '(' — so "Attend to the invoices. Then schedule a meeting." does NOT match.
#
# NOTE: under re.VERBOSE the literal "1:1" is fine; do not add spaces around it.
_ATTENDANCE_ACTION_RE = re.compile(
    r"""^\s*
        (?:[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)?\s+to\s+)?      # optional "<Name> to "
        (?:attend|join|be\s+(?:at|on|in)|sit\s+in\s+on|show\s+up\s+for|
           participate\s+in|dial\s+(?:in)?to|hop\s+on|call\s+in\s+to)
        \b
        (?:\s+[\w'-]+)*?
        \s+
        (?:meeting|call|sync|stand-?up|session|webinar|conference|
           huddle|check-?in|1:1|one-on-one)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_attendance_action_item(text: str) -> bool:
    """True when `text` describes attending/joining an event (a calendar event
    that resolves when its time passes), rather than producing a deliverable.

    Used to drop *past-due* attendance items from the overdue view: a meeting
    that already happened has nothing left "to do" and must not read as overdue.
    Future attend-items are NOT dropped by the caller — they are valid reminders.
    """
    if not text:
        return False
    return bool(_ATTENDANCE_ACTION_RE.search(text))
