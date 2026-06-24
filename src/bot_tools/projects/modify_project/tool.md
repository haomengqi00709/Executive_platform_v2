---
action: true
routing: "'mark Nexus paused', 'set the IPS project to needs_attention', 'ignore the X project' — change one field on a project"
---
Change one field on a project in the store. The change is immediate and reflected everywhere
(dashboard + bot). Use for "mark X paused/completed", "set X to needs_attention", "ignore the X project".
index_or_hint: pass exactly what the user referred to — a word from the project's NAME when they name
it (e.g. user says "the IPS project" → pass "IPS"; "mark Nexus paused" → pass "Nexus"). ONLY pass a
number when the user actually said a number ("mark project 2"). Do NOT convert a named project into a
position based on a list shown earlier — that resolves to the wrong project.
field: one of status, momentum, category, summary, next_action, name, deadline, ignore.
value: the new value. status ∈ ongoing / needs_attention / paused / early_stage / completed;
       momentum ∈ accelerating / steady / slowing / stalled; ignore ∈ true / false.
