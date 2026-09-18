# ADR-002: Centralise the confirmation gate behind a single Action Gateway

Status: **Proposed** — decision needed before building the Outlook / calendar / inbox flows
Date: 2026-09-18
Relates to: ADR-001

## Context

The Gmail flow works: request → log → approval → branch → send-or-reject → log outcome.
The stated plan is to duplicate that shape for Outlook send, then Google Calendar,
then Outlook Calendar, then the incoming-email reply flow.

That is **four more copies of the security-critical part of the system**, and then a
migration of all five into the production stack.

## Problem

### 1. The gate is copy-pasted policy, and copy-pasted policy drifts

In the current shape, "is this action allowed to execute?" is expressed as *a branch
someone drew on a canvas*. Nothing structurally prevents the sixth workflow from
wiring the send node to the wrong output of the IF node. Nothing detects it if it
happens. The failure mode is silent: it looks identical to a working flow until it
sends something unapproved.

This directly contradicts ADR-001 invariant 1 — tier is supposed to be declared at
the tool boundary, but here it is implicit in per-workflow topology.

### 2. Approve-by-link is a real vulnerability, not a theoretical one

If the approve/reject buttons are URLs delivered by **email**, two things are true:

- **The URL is a bearer capability.** Anyone who obtains it — forwarded mail, a shared
  mailbox, an archive, a backup — can approve. There is no proof the *CEO* approved,
  only that *someone with the link* did. That fails the audit requirement in ADR-001.
- **Enterprise mail security scanners prefetch links.** Microsoft Defender for
  Office 365 Safe Links, Proofpoint URL Defense, Mimecast and others fetch and
  "detonate" URLs in inbound mail to check them. A `GET`-triggered approve endpoint
  can therefore be **auto-approved by a security scanner**, with no human involved.
  This is a known class of breakage for one-click confirm/unsubscribe flows.

For T2 this is bad. For T3 — placing calls, messaging unknown contacts — it is
disqualifying, and it is exactly the tier ADR-001 says must *never* be auto-approved.

### 3. Migration cost multiplies

Five bespoke approval implementations means five things to port, five things to
re-verify, five chances for behaviour to change during migration.

## Decision (proposed)

Extract **one** Action Gateway sub-workflow that every flow calls. It owns, in one place:

```
  classify(tool, payload) -> tier          # from a static registry, not from the caller
  log_intent(...)                          # before anything else happens
  if tier <= T1:  execute
  if tier >= T2:  request_confirmation -> verify_approval -> execute
  log_outcome(...)                         # on every path, including reject and error
```

Caller workflows then contain **no approval logic at all**. They build a payload,
call the gateway, and handle the result. Gmail send, Outlook send, calendar create,
calendar move and inbox-reply become thin callers.

### Confirmation channel

Approval must not be a GET link in an email. In order of preference:

1. **In-app confirmation** (the stated end state) — authenticated session, full
   control over presentation and audit.
2. **Telegram inline keyboard** as the interim channel. `callback_data` goes back
   through the bot, and the bot is already locked to a single Telegram user ID.
   This gives an identity-bound approval rather than a link-bound one, and it is the
   reason the Telegram bot already exists. Approvals are not prefetchable by a scanner.

Either way the gateway must verify: correct approver identity, approval token is
single-use, token is bound to *this specific payload digest*, and the token has expired
if it is older than N minutes. An approval that does not name what it approved is
not an approval.

### Honest limitation

**An n8n sub-workflow is a convention, not a security boundary.** Anyone with n8n
editor access can call the send node directly and bypass the gateway entirely. This
ADR reduces drift and makes migration tractable; it does **not** make the prototype
enterprise-secure. The real boundary arrives when the gateway becomes a service that
holds the only credentials that can send — at which point bypassing it is not
possible, because no other component can authenticate to Microsoft or Google.

That is the shape the production migration should target, and building the gateway
now means the migration is "move one component" rather than "rewrite five."

## Consequences

- Slight up-front cost before the Outlook flow, paid back on flows 2 through 5.
- One place to add rate limits, recipient allowlists, and T3 handling later.
- One audit log schema instead of five.
- The credential-holding service in production has an obvious, already-specified
  boundary to inherit.

## Open question

Whether to build the gateway *now*, before the Outlook flow, or to finish Outlook as
a direct Gmail copy first and refactor after. Building it first is cheaper overall;
finishing Outlook first gets a working second channel sooner. **Recommendation: build
the gateway first**, because the Outlook flow is currently blocked on OAuth anyway,
so the gateway costs no calendar time on the critical path.
