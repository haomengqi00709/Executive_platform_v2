---
action: true
routing: "'mark Nexus paused', 'set the IPS project to needs_attention', 'ignore the X project' — change one field on a project"
---
Change one field on a project in the store. The change is immediate and reflected everywhere
(dashboard + bot). Use for "mark X paused/completed", "set X to needs_attention", "ignore the X project".
index_or_hint: the project's #N (as just shown), its exact id, or a word from its name.
field: one of status, momentum, category, summary, next_action, name, deadline, ignore.
value: the new value. status ∈ ongoing / needs_attention / paused / early_stage / completed;
       momentum ∈ accelerating / steady / slowing / stalled; ignore ∈ true / false.
