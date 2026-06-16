# An rfc-reviewer agent: a review pass for the decision, not just the code

- **Status:** Accepted
- **Date:** 2026-06-16
- **Author:** agent-native-setup team

## Context

RFCs are the highest-leverage, hardest-to-reverse artifact the scaffold produces —
they decide what the code will become. Yet the RFC machinery enforces only
*existence* and *lifecycle*, never *quality*:

- `rfc_needed.py` forces an RFC (or a waiver) to exist for structural changes.
- `sync_rfc_status.py` keeps it in the folder its Status names.
- `/rfc` scaffolds one; its only quality step is "show me the draft."
- `code-reviewer` judges a *diff* against the four execution principles — it never
  reads a proposal.

So the project already treats *code* as needing an adversarial review pass before
"done" (`code-reviewer` + `/review` + the contract's feedback-loops line), while the
*decision* the code implements gets none. In an agent-native repo the RFC author is
usually an agent, so self-review by the authoring context is weak — the value is in
an *independent* pass, exactly how `code-reviewer` is used on a diff.

## Decision

Ship an `rfc-reviewer` subagent that mirrors the `code-reviewer` pattern, with the
same three touch-points:

1. **`.claude/agents/rfc-reviewer.md`** — a read-only agent (Claude, with docs) that
   judges an RFC's *decision quality*: is the problem stated (not an assumed
   solution); is the simplest viable option chosen with an honest "why"; are
   alternatives genuinely weighed; are consequences honest about costs and what's
   given up; is the reversibility framing accurate; does it conflict with or silently
   overlap an existing/`done`/superseded RFC.
2. **`/rfc` trigger** — its draft step runs `rfc-reviewer` and resolves findings
   before showing the draft.
3. **Contract line** — the "When to write an RFC" section points at it, gated on
   agents (the way the feedback-loops bullet points at `code-reviewer`).

It is advisory and scales down for a small RFC — a one-line decision gets one-line
scrutiny — so it adds judgment, not ceremony.

## Consequences

The decision artifact gets the same independent-review discipline the code already
has. Drift between "an RFC exists" and "the RFC is sound" closes. Cost: one more
agent to keep in step with the contract, and a slightly longer `/rfc` flow. It's
read-only and non-blocking, so a weak review never wedges the process — at worst it
adds noise. The only guardrail against that noise is the agent prompt's calibration
("few high-confidence findings," "scale to the RFC," "don't manufacture objections"),
not a mechanical floor; an over-eager reviewer on a trivial RFC is the realistic
failure mode, and it's a prompt-tuning fix, not a process one.

This change is itself cheap to reverse — delete one agent file, one command step,
and one contract sentence — so it's a low-stakes door. It gets an RFC anyway because
it touches the contract surface and the `/rfc` flow, which `enforce-rfc-on-new-dependency`
treats as RFC-worthy by convention.

## Alternatives considered

- **A contract instruction alone, no agent.** Cheapest, but "by memory" — the
  opposite of the project's mechanical-enforcement ethos — and a self-reviewing
  author lacks the independent perspective that makes the pass worth running.
- **Fold it into `code-reviewer`.** Different input (a proposal, not a diff) and
  different criteria (decision quality, not execution); merging dilutes both prompts.
- **A mechanical gate.** `rfc_needed` already checks *presence*; *quality* (did it
  pick the simplest option?) can't be linted.
- **A "parallel"/always-on reviewer.** An RFC is reviewed once, at draft or before
  Accepted — not continuously on every change; the `/rfc` flow is the right trigger.

This is *not* the `architecture-reviewer` subagent that `route-to-security-review`
rejected. That one would have stood watch over the codebase's design, duplicating
what the RFC process and `tests/test_architecture.py` already do. This reviews the
RFC *document* — it's what makes "the RFC process covers design review" actually
hold, rather than a second reviewer competing with it.
