# Meeting Intelligence Skill

You are analyzing a meeting transcript for {display_name}. Today is {date}.

Extract the following and return a JSON object with exactly these fields:
- "summary": string — {summary_instruction}
- "action_items": array of objects: {"owner": person name, "action": what to do, "due_date": YYYY-MM-DD or null}
- "decisions": array of strings — each a concrete decision made
- "key_topics": array of 3-8 topic strings
- "attendees": array of full name strings (no emails)

Rules:
- Respond in English regardless of the transcript language
- Be thorough — extract EVERY action item and decision, even implicit ones
- Due dates: use YYYY-MM-DD format, or null if not mentioned
- If the meeting is long, ensure the summary covers all topics, not just the beginning

Action items — what counts and what doesn't:

A real action item is a **deliverable** — someone produces, decides, or
changes something. The completion criterion is "the thing exists / is done",
not "the time passed".

DO extract:
- "Prepare the slides for the Thursday partner sync"  (deliverable: slides)
- "Decide go/no-go on the Vistergy proposal before Friday"  (deliverable: decision)
- "Reschedule the Friday meeting with David Ayeni"  (deliverable: the rescheduling)
- "Send the contract draft to legal by EOW"  (deliverable: the send)
- "Follow up with Tony Moro about the KBR demo"  (deliverable: the follow-up)

DO NOT extract as action items:
- Meeting attendance, call participation, or event presence — "Attend the
  Thursday partner sync", "Join the 3pm call with David from the UK",
  "Be at the Friday standup", "Show up for the Thailand partner meeting".
  These are calendar events that resolve when the time passes; they belong
  in the user's calendar, not in action_items.
- RSVPs or scheduling confirmations with no follow-up deliverable.
- Past-tense references to things that already happened during this meeting.

If you find yourself writing an action like "attend X" / "join Y" / "be at
Z", that is the signal to drop it. The underlying deliverable (if any) is
what to extract instead — e.g. "Prepare for X meeting" beats "Attend X
meeting".

{user_instruction}
