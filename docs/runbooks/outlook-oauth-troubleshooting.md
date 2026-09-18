# Runbook: Microsoft Outlook OAuth2 fails in n8n (popup closes / crashes)

Status: active blocker
Applies to: `Microsoft Outlook OAuth2 API` credential in n8n

## Why this runbook exists

"The popup closes before I can connect" is a **symptom with at least five distinct
causes**. Public n8n threads for this symptom are mostly unresolved because people
guess at fixes instead of reading the actual error. Microsoft *always* returns a
specific `AADSTS#####` code — the popup just disappears before you can read it.

**Step 0 is therefore not optional: capture the real error first.** Everything
below is keyed off that code.

## Step 0 — Capture the actual error

The popup is a normal browser window. Stop it from closing:

1. In n8n, open the credential and click **Connect my account**.
2. In the popup, press `F12` immediately (or right-click → Inspect).
3. In DevTools → **Network** tab, tick **Preserve log**. This survives the redirect
   and the close.
4. Re-run the sign-in. Look at the request to `login.microsoftonline.com/.../authorize`
   and the redirect that follows it.
5. The failing redirect carries `?error=...&error_description=AADSTS#####...`.
   **Record that code.**

Also check, in order:
- **n8n server logs** at the moment of failure (self-hosted: `docker logs -f n8n`).
- **Entra admin centre → Monitoring → Sign-in logs** → filter by your app. This
  shows the failure server-side even when the popup gives you nothing. This is the
  most reliable source and needs no DevTools.

Do not proceed past this step by guessing. Match the code below.

## Decision tree by error code

### `AADSTS50011` — redirect URI mismatch
By far the most common cause of an instantly-closing popup.

The match is **byte-for-byte and case-sensitive on the path**, and **one trailing
slash breaks it**.

1. In n8n, copy the **OAuth Redirect URL** shown in the credential modal *verbatim*.
2. In Entra → your app → **Authentication** → **Platform configurations**, confirm
   that exact string is registered.
3. **Confirm it is registered under the `Web` platform, not `Single-page application`.**
   The correct URI under the wrong platform type still throws `AADSTS50011`. SPA
   implies PKCE without a client secret; n8n is a confidential client and needs `Web`.
   Verify in the app **Manifest**: the entry must sit under `web.redirectUris`, not
   `spa.redirectUris`.

**Self-hosted trap:** if n8n shows `http://localhost:5678/rest/oauth2-credential/callback`,
your instance does not know its own public URL. Microsoft will never accept that.
Set all of these to the public domain and restart:

```
N8N_HOST=n8n.example.com
N8N_PROTOCOL=https
N8N_PORT=5678
WEBHOOK_URL=https://n8n.example.com/
N8N_EDITOR_BASE_URL=https://n8n.example.com/
```

Then re-read the Redirect URL from the credential modal — it must now be
`https://n8n.example.com/rest/oauth2-credential/callback` — and register *that*.

> If TLS terminates at a reverse proxy (Caddy/nginx/Cloudflare Tunnel), n8n still
> needs `N8N_PROTOCOL=https` so it *generates* `https://` links, and the proxy must
> forward `X-Forwarded-Proto`. Getting this wrong produces an `http://` callback that
> Microsoft rejects.

### `AADSTS50020` / `AADSTS700016` — account type mismatch
The app registration's **supported account types** do not include the account you
are signing in with. Classic case: app registered single-tenant, signing in with a
personal `outlook.com` / `hotmail.com` account.

n8n's own documentation specifies: **"Accounts in any organizational directory
(Any Azure AD directory - Multi-tenant) and personal Microsoft accounts."**

Fix in Entra → app → **Authentication** → *Supported account types*. If the app was
created under a personal MSA, you must open the portal with `isMSAApp=true`.

### `AADSTS7000215` / `AADSTS7000222` — invalid or expired client secret
- You almost certainly pasted the **Secret ID** instead of the **Secret Value**.
  The Value is shown **exactly once**, at creation. If you navigated away, delete
  the secret and create a new one.
- `AADSTS7000222` specifically means the secret **expired**. Azure secrets have a
  max lifetime (24 months). There is a known recurring cluster of n8n Outlook
  failures caused purely by expiry. **Record the expiry date somewhere you will see it.**

### `AADSTS65001` / "Need admin approval"
Your account is governed by an Entra tenant that requires admin consent. A tenant
admin must grant consent for the app before any user can complete the flow. n8n's
docs call this out explicitly. Self-service is impossible here — it needs the admin.

### No error code at all / popup opens then hangs then dies
- **Third-party cookie blocking / tracking protection.** n8n's OAuth handshake is
  cross-origin. Brave Shields, Safari ITP, Firefox strict mode, and hardened Chrome
  profiles can kill the popup silently. **Test once in a clean Chrome profile with
  shields down** — this is a 60-second test that eliminates a whole branch.
- **Popup blocker** eating the window.
- **`ETIMEDOUT` to `login.microsoftonline.com` in n8n logs** → your n8n *server*
  cannot reach Microsoft outbound (egress firewall / proxy). Note this is distinct
  from your browser reaching Microsoft; the token exchange is server-side.
  Test from the container: `docker exec -it n8n wget -qO- https://login.microsoftonline.com`

## Required scopes

Whatever you do, include **`offline_access`**. Without it Microsoft issues no refresh
token, the credential appears to connect, and then dies ~1 hour later. There is a
known n8n bug where this specific failure is masked by a
`TypeError: dummy.stack.replace is not a function` instead of the real OAuth error —
so a confusing `dummy.stack` error downstream almost always means *refresh token*,
not whatever the message says.

For the send-email flow: `offline_access`, `Mail.Send`, `Mail.ReadWrite`, `User.Read`.
For the calendar work that comes next: add `Calendars.ReadWrite`.

## If you are on n8n Cloud

You have two paths, and it is worth knowing which you are on:
- **n8n-managed OAuth** — no Azure app at all. If this is failing, none of the Azure
  fixes above apply; it is n8n-side and the fallback is to switch to your own app
  registration (which you want anyway for an enterprise system — see ADR-002).
- **Your own Azure app** — everything above applies.

For ALIA, **use your own Azure app registration regardless.** A managed shared OAuth
client is not acceptable for a production enterprise system: you get no control over
scopes, no tenant-level audit trail, and no ability to revoke independently.

## Escalation

If Step 0 yields a code not listed here, record the code, the n8n version, and
whether you are Cloud or self-hosted, and bring all three back. Do not start
changing settings without a code — that is how these threads stay open for months.
