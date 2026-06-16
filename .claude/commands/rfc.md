---
description: Scaffold a new RFC in docs/rfc/current/
---

Create a new RFC for: $ARGUMENTS

1. Pick a short kebab-case slug and today's date.
2. Copy `docs/rfc/TEMPLATE.md` to `docs/rfc/current/<YYYY-MM-DD>-<slug>.md`.
3. Fill in Context, Decision, and Consequences. Leave status as `Proposed`.
4. Run the `rfc-reviewer` subagent on the draft and resolve its findings.
5. Show me the reviewed draft before considering it done.
