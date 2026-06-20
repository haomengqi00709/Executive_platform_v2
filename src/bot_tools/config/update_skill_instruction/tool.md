---
action: false
---
Update the custom instructions for a section. These instructions override the default
AI behavior for that section on the next run. IMPORTANT: always call read_skill_instruction
first, then append your new rules to the existing content — do not discard prior rules.

section_id must be one of the keys in SECTION_IDS — see the TOOL ROUTING list
above for the catalog of available sections.
