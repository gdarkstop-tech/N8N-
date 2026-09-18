# ALIA — n8n prototype workflows

## `outlook-send-with-telegram-approval.json`

Outlook send flow (T2) with the approval step routed through **Telegram** instead of
Outlook.

### Why Telegram for the approval step

Your Outlook `sendAndWait` node is blocked on the Microsoft OAuth failure. But the
approval step never needed Outlook — it only needs *a channel to ask you on*. Your
Telegram bot is already connected and already locked to your user ID.

Two benefits:

1. **You can build and test the whole flow today.** Only the final `Send Email
   (Outlook)` node still needs the Microsoft credential.
2. **It is more secure.** A Telegram inline button is identity-bound (it comes back
   through the bot, from your user ID). An emailed approve-link is a bearer URL that
   anyone holding it can click — and enterprise mail scanners (Defender Safe Links,
   Proofpoint, Mimecast) prefetch links in mail, which can auto-approve a `GET`-based
   approve button with no human involved. See `docs/architecture/ADR-002-action-gateway.md`.

### How to paste

1. Open the JSON file, select all, copy.
2. Click onto the n8n canvas and press `Ctrl/Cmd+V`. The nodes appear wired up.

### Then fill in 4 things

| Node | What to set |
|------|-------------|
| `Request Approval (Telegram)` | `chatId` — replace `YOUR_TELEGRAM_CHAT_ID`, and attach your Telegram credential |
| `Send Email (Outlook)` | Attach the Microsoft Outlook OAuth2 credential (blocked — see runbook) |
| All three `Log *` nodes | Pick your document + sheet from the dropdowns, attach Google Sheets credential |
| — | Sheet header row must match: `request_id, channel, tier, to, subject, body, requested_at` and for outcomes `decision, outcome, decided_at` (mapping mode is `autoMapInputData`) |

To find your chat ID: message the bot, then open
`https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and read `result[0].message.chat.id`.

### Gotchas that will bite you

- **After `sendAndWait`, the original form data is gone.** The node outputs only
  `{ data: { approved: true } }`. That is why every downstream node references
  `$('Build Request').item.json.*` rather than `$json.*`. If you rename the
  **Build Request** node, you must update those references or the flow breaks.
- **If the Telegram approve buttons 404**, it is a known n8n bug where Telegram
  `sendAndWait` does not respect `WEBHOOK_URL`
  ([n8n#23489](https://github.com/n8n-io/n8n/issues/23489)). Set `WEBHOOK_URL` *and*
  `N8N_EDITOR_BASE_URL` to your public HTTPS domain and restart.
- **Approval expires after 30 minutes** (`limitWaitTime`). This is deliberate — a
  T2 approval should not sit open indefinitely. Adjust in the node's Options.
- The flow is **`bodyContentType: text`** on purpose. Outlook's Send Message node has
  known HTML handling bugs ([n8n#19781](https://github.com/n8n-io/n8n/issues/19781)).
  Switch to HTML only once you have tested it.

### Testing it before Outlook OAuth is fixed

Disable the `Send Email (Outlook)` node (select it, press `D`). The rest of the chain —
form, logging, Telegram approval, branch, outcome logging — runs end to end. That
validates the entire gate. Re-enable the send node once the credential connects.

### Reusing this for Gmail

Same graph. Swap `Send Email (Outlook)` for your existing Gmail send node and change
`channel` to `gmail` in the three Set nodes. Note this also upgrades Gmail's approval
from an emailed link to a Telegram button.
