# ADR-001: Risk-tiered action model

Status: **Accepted** (pre-existing design, recorded here for continuity)
Date: 2026-09-18

## Context

ALIA/EAIOS gives an LLM-driven assistant the ability to cause real-world side
effects on behalf of the CEO. The governing principle is that **the LLM is never the
security boundary** — the model may *propose* any action, but whether that action
executes is decided by deterministic infrastructure.

This requires a classification of actions by blast radius and reversibility.

## Decision

Every action the assistant can invoke is assigned a risk tier. The tier is a
property of the **tool definition**, not of the model's output — the model cannot
declare its own tier.

| Tier | Definition | Examples | Gate |
|------|-----------|----------|------|
| **T0** | Read-only. No state change anywhere. | Read inbox, read calendar, search documents | No confirmation |
| **T1** | Reversible, internal-only. Nothing leaves the org. | Draft an email, create an internal note | No confirmation; logged |
| **T2** | External, but reversible or low-consequence. | Send an email, create/move a calendar event | **Explicit confirmation required** |
| **T3** | Hard to reverse, or escalatory. | Place a phone call, message an unknown contact | **Always confirmed. Never auto-approved, ever.** |

### Invariants

1. **Tier is assigned at the tool boundary.** A tool's tier is declared in
   infrastructure. Model output cannot set, lower, or negotiate it.
2. **T3 has no auto-approve path.** There is no configuration, role, or "trusted
   mode" that can silently execute a T3 action. This is a hard invariant, not a default.
3. **Confirmation is per-action, not per-session.** Approving one email does not
   approve the next one.
4. **Every T1+ action is logged** — intent, tier, requester, payload digest,
   decision, decision-maker, outcome — regardless of whether it was approved,
   rejected, or errored.
5. **Rejection is a logged outcome**, not a silent no-op.

## Consequences

- Adding a new integration means classifying its operations before shipping them.
  An unclassified operation is not callable.
- The confirmation UI is on the critical path for every T2/T3 action, which is why
  the primary owner interface is **in-app** rather than Slack/Telegram/Discord: we
  need full control over how a confirmation is presented, authenticated, and recorded.
- Telegram remains a **notification and pre-authenticated approve/deny channel only**,
  not the main chat surface.

## Current implementation status (2026-09-18)

Prototyped in n8n, **not** production architecture:

- **Gmail send flow — working end to end.** Form request → log → approval message
  with approve/reject → send only on approve → outcome logged. T2 gate is real and
  observed to work.
- **Telegram bot ("Alia Company")** — created, private access mode, restricted to a
  single Telegram user ID. Intended for push notification + approve/deny.
- **Outlook send flow — blocked.** Same shape as Gmail. Blocked on an OAuth
  credential failure; see `docs/runbooks/outlook-oauth-troubleshooting.md`.
- **Twilio / voice — on hold.** Signup blocked by a phone-verification error. This
  is T3 territory and is deliberately deprioritized.

The tier model above is the design intent. The n8n prototype implements it
*per workflow*, which does not satisfy invariant 1 in a durable way — see ADR-002.
