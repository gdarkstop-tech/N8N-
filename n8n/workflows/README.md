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
| `incoming-email-triage-gmail.json` | Read new mail → summarise → draft reply → approve → send | nothing |

## How to paste

Open a file, select all, copy, click the n8n canvas, `Ctrl/Cmd+V`. Nodes arrive wired.

## Why every approval goes through Telegram

Your Outlook `sendAndWait` node is blocked on the Microsoft OAuth failure. The approval
step never needed Outlook — it needs *a channel to ask you on*, and your Telegram bot is
already connected and locked to your user ID.

Two consequences:

1. **Four of five flows work today.** Only the two Outlook *action* nodes need the
   Microsoft credential.
2. **It is more secure than an emailed approve-link.** An emailed link is a bearer
   capability — anyone holding it approves, and you cannot prove it was you. Worse,
   enterprise mail scanners (Defender Safe Links, Proofpoint, Mimecast) prefetch links
   in inbound mail, which can auto-click a `GET` approve button with no human involved.
   A Telegram inline button is identity-bound and not prefetchable.

## Setup, once

| Where | What |
|---|---|
| Every `Request Approval (Telegram)` | replace `YOUR_TELEGRAM_CHAT_ID`, attach Telegram credential |
| Every `Log *` node | pick document + sheet from the dropdowns |
| `Anthropic Chat Model` (triage flow) | attach Anthropic credential |
| Outlook nodes | Microsoft credential — see `docs/runbooks/outlook-oauth-troubleshooting.md` |

Chat ID: message the bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates`,
read `result[0].message.chat.id`.

Sheets use `autoMapInputData`, so the **header row must match the field names** the
Set nodes emit. Union of all of them:

```
request_id, channel, tier, to, subject, body, requested_at,
title, conflict_count, from, injection_detected,
decision, outcome, decided_at
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

## Security notes on the triage flow

Incoming email is **untrusted input reaching an LLM**. Three controls are built in:

1. **The email is delimited and labelled as data.** The system prompt states the sender
   is not the model's principal and that instructions inside `<untrusted_email>` must be
   ignored. This is defence-in-depth, *not* a guarantee — prompt injection is not solved
   by prompting.
2. **The model never chooses the recipient.** `Send Reply (Gmail)` uses `messageId` from
   `Extract Email`, so Gmail resolves the recipient from the original thread. Even a
   fully successful injection cannot redirect the reply — it is structurally impossible,
   which is the only kind of control worth relying on. This is the ADR-001 principle in
   practice: the LLM supplies body text, infrastructure decides where it goes.
3. **Injection attempts surface in the approval message.** The model sets
   `injection_detected`, and the Telegram message shows a 🚨 banner. Treat this as a
   signal to read carefully, never as a filter you can trust.

`Parse Draft` also fails safe: if the model returns malformed JSON, the flow does not
crash and does not send an empty reply — it flags `parse_error` and shows raw output.

**What is still not protected:** the model reads the whole email body, so a malicious
email can waste tokens or attempt to influence the summary you read. Approval is the
backstop — read the summary critically, especially with the 🚨 banner.

## Model choice

The triage flow pins `claude-opus-5` on the `Anthropic Chat Model` sub-node. The node is
deliberately a *separate sub-node* from the chain: swap it for OpenAI, Gemini, or any
other provider and the chain is unchanged. That is the provider-independence principle
holding at the prototype layer.
