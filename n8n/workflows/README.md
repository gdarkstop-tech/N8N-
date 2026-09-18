# ALIA — n8n prototype workflows

Telegram is the interface. Nothing routes approvals through email, and no other chat
surface is assumed.

| File | Nodes | Action node blocked on |
|---|---|---|
| `gmail-send-with-approval.json` | 18 | — |
| `outlook-send-with-approval.json` | 18 | Outlook OAuth |
| `calendar-google-create-with-approval.json` | 19 | — |
| `calendar-outlook-create-with-approval.json` | 19 | Outlook OAuth + **calendar must be picked** |
| `incoming-email-triage-gmail.json` | 26 | — |

These replace every earlier version. The old `*-with-telegram-approval.json` files are
deleted — two of them carried a bug (see *Corrections* below).

## Before you paste: three values

1. `YOUR_TELEGRAM_CHAT_ID` — where messages are sent
2. `YOUR_TELEGRAM_USER_ID` — who is allowed to approve (`approverIds`)
3. Outlook Calendar only: the `Create Event (Outlook)` calendar, which **must** be
   picked from the dropdown. An empty `calendarId` throws `Calendar ID is required`
   at runtime — verified in the node source.

Both IDs come from `https://api.telegram.org/bot<TOKEN>/getUpdates`:
`result[0].message.chat.id` and `result[0].message.from.id`. In a private 1:1 chat they
are the same number; in a group they differ.

**An empty `approverIds` means anyone who can see the message can approve.**

## Audit logging

Every workflow writes to the **`Assistant Action Log`** Data Table
(`n8n-nodes-base.dataTable`, `operation: insert`, `dataTableId` by name). No Google
Sheets nodes remain anywhere — that is checked by the validator.

Each workflow has **exactly one** `Audit Log` node. All six outcome branches feed it,
and every branch writes the identical 13 columns:

```
request_id  dedupe_key  ts       channel   action   tier   approver_id
subject     target      importance  decision  outcome  detail
```

Create these columns in the Data Table before first run. `decision` and `outcome` are
closed vocabularies:

| `decision` | `outcome` |
|---|---|
| `approved`, `rejected`, `timed_out`, `duplicate_suppressed`, `validation_failed`, `auto_filtered` | `succeeded`, `not_sent`, `not_created`, `not_surfaced`, `failed` |

`approver_id` records the **Telegram user ID that actually tapped the button**, taken
from the callback payload — not from configuration. That is what makes the log
evidence rather than an assumption.

## Flow shape (identical in all five)

```
trigger → build & validate → valid? ─no→ Outcome: Invalid ─────────┐
                              │yes                                  │
                    idempotency probe → duplicate? ─yes→ Outcome: Duplicate ─┤
                              │no                                   │
                      [conflict probe / LLM triage]                 │
                              ↓                                     │
                    Telegram approval (one-tap, restricted)          │
                              ↓                                     │
                  approved? ─yes→ action ─ok→  Outcome: Succeeded ───┤
                     │              └─err→     Outcome: Failed ──────┤
                     └no→ decided? ─yes→       Outcome: Rejected ────┤
                                    └no→       Outcome: Timed Out ───┤
                                                                     ↓
                                                              Audit Log
```

## What changed, and why

### Timeouts now actually exist

`limitWaitTime` is a **fixedCollection** read at `options.limitWaitTime.values`. The
earlier files set it as a bare boolean, which n8n silently ignores — meaning those
approvals would have waited **forever**. Now:

```json
"limitWaitTime": { "values": { "limitType": "afterTimeInterval",
                               "resumeAmount": 4, "resumeUnit": "hours" } }
```

Send and calendar moved 30 min → **4 hours**. Thirty minutes is not an executive
window; a request sent before a meeting would have expired unseen. Triage stays at
**12 hours**, since inbound mail is less time-boxed.

### A timeout is now a distinct, logged outcome

When the wait expires, n8n resumes with the node's *input*, not a decision — so
`$json.data.approved` is absent. A single IF would score that as "rejected" and the log
would claim you declined something you never saw. Two chained IFs now separate them:

- `data.approved === true` → approved
- `data.approved !== undefined` → rejected (you actually decided)
- otherwise → **timed out**

All three are audited. Nothing ends silently.

### Idempotency is keyed on content, not execution

A double form submit creates two executions with two different execution IDs, so an
execution-keyed guard could never match. The key is an FNV-1a hash of
`channel + recipients + subject + body` (calendar: `title + start + end + attendees`;
triage: the Gmail `message_id`, already a natural key). Before any send, the flow
queries the audit table for that `dedupe_key` with `outcome = succeeded` and suppresses
a repeat.

Scope: this catches double submits and repeated approvals of identical content. It is
not a distributed lock — two *simultaneous* executions can both read "no prior row"
before either writes. For a prototype at one-user volume that race is not reachable;
in production the gateway service owns this.

### Calendar conflicts: widened window, overlap decided locally

The probe window is now widened by **±12 hours** and the row limit raised from 20 to
250. Overlap is then decided in code with the real test:

```
existing.start < requested.end  AND  existing.end > requested.start
```

Your instinct was right, with a nuance: Google's `timeMin`/`timeMax` *do* already
return overlapping events, so Google was not missing them — but **the limit of 20
was**, silently, on any busy day. Outlook's filter semantics differ from Google's.
Deciding overlap locally from a wider pull is correct under both, so the flows no
longer depend on which provider is behind them.

### Datetime validation before approval

Start and End are parsed; the flow rejects unparseable dates, `end <= start`, events
longer than 7 days, and start times in the past. Invalid requests are audited as
`validation_failed` and **never reach approval** — so you are not asked to approve
something that cannot execute.

### HTML, CC and BCC

Both send flows now take `CC`, `BCC` and a `Format` dropdown (Text/HTML), mapped to
`options.ccList`/`bccList` on Gmail and `additionalFields.ccRecipients`/
`bccRecipients`/`bodyContentType` on Outlook. All addresses are validated
deterministically before approval. HTML is off by default: Outlook's Send Message node
has known HTML handling bugs ([n8n#19781](https://github.com/n8n-io/n8n/issues/19781)).

### Action failures are audited

Every action node carries `onError: continueErrorOutput` with its own
`Outcome: … Failed` branch. Previously, if Gmail or the calendar API rejected the call,
the workflow errored and **no audit row was written at all** — the most important event
(an approved action that did not happen) was the one least likely to be recorded.

## Telegram message correctness

### You get the full email, not just the summary

In the triage flow the complete original body is sent as its own message(s) **before**
the approval prompt, so you read what you are replying to. Telegram caps a message at
4096 characters, so the body is chunked at 3500 on paragraph → line → hard-cut
boundaries. A test asserts chunking loses no words, including a single token longer
than the cap.

The approval message then carries: priority, sender, subject, category, body length,
summary, and the drafted reply.

### Formatting will not break on real email

n8n hardcodes `parse_mode: 'Markdown'` on `sendAndWait`. Legacy Markdown throws
`Bad Request: can't parse entities` on any unmatched `*`, `_`, `` ` ``, `[`, `]` — which
real email contains constantly (`*urgent*`, `snake_case`, `[1]`). Escaping is
unreliable in legacy mode, so untrusted text is passed through `mdSafe()`, which
replaces those five characters with spaces.

For the full-body messages we control `parse_mode`, so those use **HTML**, whose
escaping (`&`, `<`, `>`) is total and lossless. That is why the original email arrives
character-exact while the approval prompt is lightly de-punctuated.

### Arabic / RTL

Arabic is detected by Unicode range and the block is prefixed with U+200F (RLM) so a
mixed LTR-label / RTL-content line renders right-to-left. Tested both directions.

## Verification status

Run `validate.py` output — all five pass:

- graph integrity, no dangling connections
- every `$('Node')` expression resolves to a node in the same workflow
- no unreachable nodes, no duplicate ids or names
- **no Google Sheets nodes remain**
- every outcome node emits exactly the 13 audit columns, in the same order
- exactly one audit insert per workflow; every outcome feeds it
- every approval node: `chatApproval: true`, non-empty `approverIds`,
  `unauthorizedReplyText` present, `limitWaitTime` a proper fixedCollection,
  `appendAttribution: false`
- `node --check` on all 14 Code nodes
- 23 behavioral assertions on the helpers (hashing, Markdown safety, HTML escaping,
  chunking fidelity, address validation, RTL)

**Not verified:** none of this has run against your live n8n, Google, Microsoft,
Anthropic or Telegram credentials. Node schemas were read from n8n source at `master`;
if your instance is older, a `typeVersion` may differ. Treat the first execution of
each flow as the real test.

## Corrections to what I shipped earlier

Two real bugs in the previous files, both now fixed:

1. **`limitWaitTime` as a boolean did nothing.** Those approvals would have waited
   indefinitely, not 30 minutes.
2. **Action-node failures wrote no audit row**, so a failed send left no trace.

A third thing I got wrong earlier in conversation, already corrected in the last
round: `chatApproval` defaults to `false`, which renders Telegram buttons as browser
links carrying the same bearer-link weakness as the emailed approval. All approval
nodes now set it explicitly.
