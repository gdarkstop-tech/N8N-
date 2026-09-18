# ALIA — n8n prototype workflows

Five paste-ready flows. Every one implements the same T2 gate from
`docs/architecture/ADR-001-risk-tiered-action-model.md`:

```
request → log intent → ask for approval → branch → act or don't → log outcome
```

| File | What it does | Blocked on |
|---|---|---|
| `gmail-send-with-telegram-approval.json` | Send Gmail, approval via Telegram | nothing |
| `outlook-send-with-telegram-approval.json` | Send Outlook mail, approval via Telegram | Outlook OAuth (send node only) |
| `calendar-google-create-with-approval.json` | Read schedule, detect conflicts, create event | nothing |
| `calendar-outlook-create-with-approval.json` | Same, Outlook Calendar | Outlook OAuth |
| `incoming-email-triage-gmail.json` | Filter out spam/bulk, rate importance, summarise, draft reply, approve, send | nothing |

## How to paste

Open a file, select all, copy, click the n8n canvas, `Ctrl/Cmd+V`. Nodes arrive wired.

## Why every approval goes through Telegram

Your Outlook `sendAndWait` node is blocked on the Microsoft OAuth failure. The approval
step never needed Outlook — it needs *a channel to ask you on*, and your Telegram bot is
already connected and locked to your user ID.

Two consequences:

1. **Four of five flows work today.** Only the two Outlook *action* nodes need the
   Microsoft credential.
2. **It replaces the emailed approve-link**, which is a genuine weakness: that link is a
   bearer capability — anyone holding it approves, and you cannot prove it was you.
   Worse, enterprise mail scanners (Defender Safe Links, Proofpoint, Mimecast) prefetch
   links in inbound mail, which can auto-click a `GET` approve button with no human
   involved.

### One-tap in-chat approval is not the default — these flows turn it on

n8n's Telegram `sendAndWait` has **two** approval modes, and the difference matters:

| | Default (`chatApproval: false`) | What these flows set (`chatApproval: true`) |
|---|---|---|
| Button type | `url` — opens a browser | `callback_data`, HMAC-signed |
| Where approval happens | a web page | inside the Telegram chat, one tap |
| Who can approve | anyone with the link | only the Telegram user IDs in `approverIds` |
| Bearer-link risk | **yes, still present** | no — nothing leaves Telegram |

In the default mode the Telegram button is *still a link*, so it carries the same
bearer-URL weakness as the emailed version — it is just delivered over Telegram instead.
Only `chatApproval: true` plus `approverIds` makes approval genuinely identity-bound.

**Requirements for one-tap mode:** the n8n instance must be reachable over **public
HTTPS** (not `localhost`, not plain HTTP), and the bot's webhook must be free or owned by
a Telegram Trigger on the same instance. If those aren't met, n8n **silently falls back
to link buttons** and logs a warning — so check your n8n logs the first time and confirm
you are not quietly running in the weaker mode.

`appendAttribution: false` is set on every approval node, so no "This message was sent
automatically with n8n" line is appended.

## Setup, once

| Where | What |
|---|---|
| Every `Request Approval (Telegram)` | replace `YOUR_TELEGRAM_CHAT_ID` **and** `YOUR_TELEGRAM_USER_ID`, attach Telegram credential |
| Every `Log *` node | pick document + sheet from the dropdowns |
| `Anthropic Chat Model` (triage flow) | attach Anthropic credential |
| Outlook nodes | Microsoft credential — see `docs/runbooks/outlook-oauth-troubleshooting.md` |

Chat ID: message the bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates`, read
`result[0].message.chat.id`. Your **user ID** (for `approverIds`) is
`result[0].message.from.id` in the same response — in a private 1:1 chat with the bot
these two numbers are the same, but they differ in groups, so set both from the response
rather than assuming.

Leaving `approverIds` empty means **anyone who can see the message can approve**. Set it.

Sheets use `autoMapInputData`, so the **header row must match the field names** the
Set nodes emit. Union of all of them:

```
request_id, channel, tier, to, subject, body, requested_at,
title, conflict_count, from, importance, injection_detected,
filter_reason, decision, outcome, decided_at
```

Simplest approach: one `alia_audit_log` sheet with all of those as headers, used by
every Log node in every flow. That also gives you one audit table instead of five.

## Gotchas that will bite you

- **After `sendAndWait`, upstream data is gone.** The node outputs only
  `{ data: { approved: true } }`. Every downstream node therefore references
  `$('Build Request')` / `$('Parse Draft')` / `$('Extract Email')` explicitly.
  **Rename those nodes and the flows break.**
- **Telegram approve buttons 404** → known n8n bug where Telegram `sendAndWait` ignores
  `WEBHOOK_URL` ([n8n#23489](https://github.com/n8n-io/n8n/issues/23489)). Set
  `WEBHOOK_URL` *and* `N8N_EDITOR_BASE_URL` to your public HTTPS domain, restart.
- **Outlook send is `bodyContentType: text`** on purpose — the node has known HTML
  handling bugs ([n8n#19781](https://github.com/n8n-io/n8n/issues/19781)). Switch to
  HTML only after testing.
- **Calendar `primary`** is set as resource-locator `mode: "list"`. The `id` mode
  validates against an email regex, so `primary` is only legal in list mode. Re-pick
  from the dropdown if it doesn't resolve on your instance.
- **Gmail trigger field casing varies by n8n version.** `Extract Email` defensively
  tries `$json.from || $json.From || $json.headers?.from`. If it comes out blank, run
  the trigger once and read the actual output shape.
- **Approval timeouts:** 30 min for send/calendar, 6 h for inbox triage. Deliberate —
  a T2 approval should not sit open forever.

## Testing before Outlook OAuth is fixed

Disable the blocked action node (select, press `D`). The rest of the chain — form,
logging, Telegram approval, branch, outcome logging — runs end to end, which validates
the entire gate. Re-enable once the credential connects.

## The triage flow — what reaches you

Two filter stages, so you only get interrupted for mail that matters.

**Stage 1 — deterministic, before the model.** Costs nothing and does not depend on
LLM judgement:
- Gmail's own labels: `SPAM`, `TRASH`, `CATEGORY_PROMOTIONS`, `CATEGORY_SOCIAL`
- bulk mail (`List-Unsubscribe` / `List-Id` headers) — newsletters, mailing lists
- `no-reply@`, `do-not-reply@`, `mailer-daemon@`, `postmaster@` senders

**Stage 2 — the model rates importance** `high` / `normal` / `low` / `noise`.
Only `high` and `normal` reach Telegram. The prompt tells it to be strict and to
choose `low` when torn, because a false interruption costs you more than a missed
low-priority note.

**VIP override.** Edit `VIP_SENDERS` at the top of `Pre-Filter (Deterministic)`.
Anyone listed bypasses *both* stages, even if Gmail mislabelled them — so a board
member landing in Promotions still reaches you.

Everything filtered out is still written to the audit log with a `filter_reason`.
Nothing is silently discarded, so you can review what was suppressed and tune the
lists. **Run it for a few days reading the log before trusting the filter.**

Replies are drafted only for `high`/`normal` mail. The prompt asks for a senior
executive register — courteous, direct, no filler — in the same language as the
incoming mail (Arabic and English), and explicitly forbids inventing facts, figures,
commitments or dates. If a real answer needs information the model does not have, it
writes a short holding reply instead of guessing.

## Security notes on the triage flow

Incoming email is **untrusted input reaching an LLM**. Four controls are built in:

1. **The email is delimited and labelled as data.** The system prompt states the sender
   is not the model's principal and that instructions inside `<untrusted_email>` must be
   ignored — including attempts to *raise the email's own importance rating* to force an
   interruption. This is defence-in-depth, **not** a guarantee; prompt injection is not
   solved by prompting.
2. **The model never chooses the recipient.** `Send Reply (Gmail)` uses `messageId` from
   `Extract Email`, so Gmail resolves the recipient from the original thread. Even a
   fully successful injection cannot redirect the reply — it is structurally impossible,
   which is the only kind of control worth relying on. This is ADR-001 in practice: the
   LLM supplies body text, infrastructure decides where it goes.
3. **Stage 1 filtering is deterministic.** Phishing and spam are dropped by Gmail labels
   and headers before the model ever reads them, so the highest-risk mail mostly never
   reaches the LLM at all.
4. **Injection attempts surface in the approval message.** The model sets
   `injection_detected` and Telegram shows a 🚨 banner. Treat it as a signal to read
   carefully, never as a filter you can trust.

`Parse Verdict` **fails loud, not silent**: if the model returns malformed JSON or an
unreadable importance rating, the email is surfaced anyway with a ⚠️ banner rather than
dropped. A parsing bug must never become a silent mail filter.

**What is still not protected:** the model reads the full body of mail that passes
stage 1, so a crafted email can attempt to influence the summary you read. Approval is
the backstop — read the summary critically, especially with a banner showing.

## Model choice

The triage flow pins `claude-opus-5` on the `Anthropic Chat Model` sub-node. The node is
deliberately a *separate sub-node* from the chain: swap it for OpenAI, Gemini, or any
other provider and the chain is unchanged. That is the provider-independence principle
holding at the prototype layer.
