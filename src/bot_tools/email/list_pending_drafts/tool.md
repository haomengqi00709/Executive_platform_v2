---
action: false
---
List all pending email drafts waiting for approval. Returns JSON with
`index` per item — index 1 is the CURRENT draft (the one approve_draft /
skip_draft will act on), indices 2+ are the queued drafts behind it.
Each item carries `to`, `subject`, `body` (truncated).
