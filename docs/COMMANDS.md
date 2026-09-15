# Cyan Server — Full Command Reference

Every `cyan` command, with a real usage example for each. Generated
against the actual CLI (`cli/main.py`) — if a flag here doesn't work,
that's a real bug, please [open an issue](../../../issues).

All commands except `login`, `start`, `stop`, `restart`, `uninstall`,
`status`, `setup`, `health`, `ports`, and `update` require you to be
logged in first (`cyan login`).

## Table of contents

- [Core](#core)
- [Websites](#websites)
- [Storage](#storage)
- [Trash](#trash)
- [Backup & restore](#backup--restore)
- [Databases](#databases)
- [Applications](#applications)
- [Tunnels](#tunnels)
- [Auth Service](#auth-service)

---

## Core

### `cyan start`
Start the agent (API + dashboard, one process, one port).
```bash
cyan start
```
Custom admin credentials on first run instead of an auto-generated password:
```bash
CYAN_ADMIN_USER=myname CYAN_ADMIN_PASSWORD=mypassword cyan start
```

### `cyan stop`
Stop the running agent.
```bash
cyan stop
```

### `cyan restart`
Stop and start in one command. Automatic recovery brings any
previously-running sites/apps back up as part of this.
```bash
cyan restart
```

### `cyan login`
Log in and cache a session token. Username is always `admin` for now —
only the password is asked.
```bash
cyan login                        # prompts for password
cyan login --password mypassword  # non-interactive
```

### `cyan status`
Live agent + system status (CPU, RAM, uptime).
```bash
cyan status
```

### `cyan setup`
Run hardware/OS/network detection and print a summary.
```bash
cyan setup
```

### `cyan up`
Bring back anything that was running before the agent last stopped
(reboot, crash, time offline). Safe to run any time — already-running
services are left alone.
```bash
cyan up
```

### `cyan update`
Check for, and optionally apply, updates via git.
```bash
cyan update                # check only
cyan update --apply        # check, then apply (fast-forward only)
cyan update --auto on      # enable background auto-check + auto-apply
cyan update --auto off     # background checks continue; auto-apply off (default)
```
Security-flagged updates (`[security]`/`CVE-` in the commit message)
apply automatically regardless of the `--auto` setting.

### `cyan uninstall`
Remove Cyan Server: stops the agent, tears down running sites/apps,
deletes `~/.cyan-server`. Asks for typed confirmation unless `--yes`.
```bash
cyan uninstall            # asks: type 'uninstall' to confirm
cyan uninstall --yes      # skip the prompt
```

### `cyan health`
Raw agent health check (status, uptime, version).
```bash
cyan health
```

### `cyan ports`
List currently listening ports on this host.
```bash
cyan ports
```

---

## Websites

### `cyan web list`
```bash
cyan web list
```

### `cyan web create <name> <site_type> <source_type> <source> <port> [--domain] [--replicas N] [--lb-policy POLICY]`
`site_type`: `static` | `node` | `python` | `php` | `react` | `docker`
`source_type`: `folder` | `git` | `docker_image`
`--replicas` (default `1`, max `8`): number of real backend instances to run behind Caddy for load balancing.
`--lb-policy` (default `round_robin`): `round_robin` | `least_conn` | `random` | `ip_hash` — only matters when `--replicas` > 1.
```bash
cyan web create mysite static folder ./my-site 8080
cyan web create api node git https://github.com/me/api.git 3000
cyan web create blog react folder ./blog-source 8081
cyan web create app docker docker_image nginx:latest 80

# Load-balanced: 3 real instances on ports 4000-4002, least-connections routing
cyan web create api node git https://github.com/me/api.git 4000 --replicas 3 --lb-policy least_conn
```

### `cyan web deploy <name>`
```bash
cyan web deploy mysite
```

### `cyan web stop <name>`
```bash
cyan web stop mysite
```

### `cyan web logs <name> [--lines N]`
```bash
cyan web logs mysite
cyan web logs mysite --lines 200
```

### `cyan web domain <name> [<hostname>]`
Connect, change, or clear (omit hostname) a domain or subdomain — live,
no redeploy.
```bash
cyan web domain mysite example.com
cyan web domain mysite api.example.com    # subdomain works the same way
cyan web domain mysite                    # clears the domain
```

### `cyan web delete <name> [--permanent]`
```bash
cyan web delete mysite                # moves to trash, restorable 30 days
cyan web delete mysite --permanent    # gone immediately
```

### `cyan web files <name> [path]`
List files inside a deployed site's folder.
```bash
cyan web files mysite
cyan web files mysite assets
```

### `cyan web edit <name> <path> [--content TEXT]`
Read (omit `--content`) or write a text file directly, no redeploy.
```bash
cyan web edit mysite index.html                          # prints current content
cyan web edit mysite index.html --content "<h1>Hi</h1>"   # overwrites it
```

### `cyan web rm-file <name> <path>`
```bash
cyan web rm-file mysite old-script.js
```

---

## Storage

### `cyan storage list [path]`
```bash
cyan storage list
cyan storage list photos
```

### `cyan storage usage`
```bash
cyan storage usage
```

### `cyan storage mkdir <path>`
```bash
cyan storage mkdir photos/2026
```

### `cyan storage share <path> [--expires-hours N]`
```bash
cyan storage share photos/vacation.jpg
cyan storage share photos/vacation.jpg --expires-hours 1
```

### `cyan storage delete <path> [--permanent]`
```bash
cyan storage delete photos/old.jpg              # moves to trash
cyan storage delete photos/old.jpg --permanent  # gone immediately
```

---

## Trash

Anything deleted from storage, websites, or SQLite databases lands here
for 30 days before being permanently purged.

### `cyan trash list`
```bash
cyan trash list
```

### `cyan trash restore <id>`
```bash
cyan trash restore 3
```

### `cyan trash empty [--yes]`
Permanently deletes everything currently in trash.
```bash
cyan trash empty            # asks: type 'empty' to confirm
cyan trash empty --yes
```

---

## Backup & restore

### `cyan backup create [--include-storage]`
```bash
cyan backup create
cyan backup create --include-storage   # also back up storage files (can be large)
```

### `cyan backup list`
```bash
cyan backup list
```

### `cyan backup config [--auto on|off] [--retention N] [--interval-hours N] [--include-storage on|off]`
With no flags, prints the current config.
```bash
cyan backup config
cyan backup config --auto off --retention 14 --interval-hours 12
```

### `cyan backup restore <filename> [--yes]`
**Destructive** — replaces the current database, sites, and databases.
Stops the agent, extracts, restarts. Your previous state is preserved
in a `.pre-restore-<timestamp>` folder, not deleted.
```bash
cyan backup restore cyan-backup-20260101T000000Z.tar.gz
cyan backup restore cyan-backup-20260101T000000Z.tar.gz --yes
```

---

## Databases

### `cyan db list`
```bash
cyan db list
```

### `cyan db create <name> [--engine sqlite|postgres]`
```bash
cyan db create myapp_db                     # SQLite (always available)
cyan db create myapp_db --engine postgres   # requires Postgres installed
```

### `cyan db status <name>`
Real file size, table list, and per-table row counts.
```bash
cyan db status myapp_db
```

### `cyan db query <name> <sql>`
Admin-only management SQL.
```bash
cyan db query myapp_db "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)"
cyan db query myapp_db "INSERT INTO users (email) VALUES ('me@example.com')"
cyan db query myapp_db "SELECT * FROM users"
```

### `cyan db delete <name> [--permanent]`
```bash
cyan db delete myapp_db              # SQLite: moves to trash
cyan db delete myapp_db --permanent  # gone immediately (always permanent for Postgres)
```

---

## Applications

### `cyan apps list`
```bash
cyan apps list
```

### `cyan apps install <manifest_path>`
```bash
cyan apps install ./my-app-manifest.yaml
```
Example manifest:
```yaml
name: example-app
type: docker
image: nginx:latest
ports:
  - 8080
requirements:
  ram: 512MB
  storage: 1GB
```

### `cyan apps start <name>` / `cyan apps stop <name>`
```bash
cyan apps start example-app
cyan apps stop example-app
```

---

## Tunnels

Worldwide access to a locally-hosted site — Cloudflare Tunnel (custom
domains, needs a Cloudflare account) or ngrok (instant public URL, no
domain needed). Fully optional.

### `cyan tunnel status`
Reports both providers — whichever is installed.
```bash
cyan tunnel status
```

### `cyan tunnel create <name> [--provider cloudflare|ngrok]`
```bash
cyan tunnel create my-tunnel                       # Cloudflare
```
(ngrok tunnels are created on demand via `connect`, not this command.)

### `cyan tunnel connect <site> [--hostname HOST] [--provider cloudflare|ngrok] [--tunnel-name NAME]`
The actual "local site, worldwide access" step — looks up the site's
real local port automatically.
```bash
# Cloudflare: requires both --hostname and --tunnel-name
cyan tunnel create my-tunnel
cyan tunnel connect mysite --hostname mysite.example.com --tunnel-name my-tunnel

# ngrok: hostname optional (random public URL if omitted)
cyan tunnel connect mysite --provider ngrok
```

**Multiple domains on one tunnel:** run `cyan tunnel connect` again with a
different site and `--hostname`, same `--tunnel-name` — one Cloudflare
tunnel can carry any number of domains, each routed to its own site's
real port via a generated `cloudflared` ingress config (not just a DNS
record with nowhere to route).
```bash
cyan tunnel connect blog --hostname blog.example.com --tunnel-name my-tunnel
cyan tunnel connect api  --hostname api.example.com  --tunnel-name my-tunnel
```

### `cyan tunnel domains [--tunnel-name NAME]`
List every domain currently connected (optionally filtered to one
tunnel).
```bash
cyan tunnel domains
cyan tunnel domains --tunnel-name my-tunnel
```

### `cyan tunnel disconnect-domain <hostname> <tunnel_name>`
Drop a domain from a tunnel's ingress config — the DNS record itself
stays in Cloudflare (there's no single `cloudflared` command to remove
that part), but traffic stops routing anywhere once it's out of the
config.
```bash
cyan tunnel disconnect-domain blog.example.com my-tunnel
```

### `cyan tunnel url [--port N]`
Get the current public ngrok URL.
```bash
cyan tunnel url
cyan tunnel url --port 8080
```

## Auth Service

Email+password authentication as a feature your own apps/sites can use —
scoped by **project** and **API key**. Real bcrypt password hashing, real
SMTP delivery of verification links/OTPs, real password policy, and a
real database-backed progressive lockout (each repeat lockout doubles
the cooldown). SMTP details are collected only when you actually
configure this feature, and are verified with a real login attempt
before being saved — nothing is stored or sent until that check passes.

### `cyan auth project-create <name> [--description TEXT]`
Creates a project and prints its API key — **shown exactly once**, copy
it immediately. Also seeds default email templates.
```bash
cyan auth project-create "My App" --description "Auth for my SaaS"
```

### `cyan auth project-list`
List every project, its SMTP/verification status, and current policy.
```bash
cyan auth project-list
```

### `cyan auth smtp <project_id> --host H --port P --email E [--use-tls/--no-tls] [--from-name NAME]`
Configure (or replace) a project's SMTP credentials. Prompts for the
app password if not piped in; performs a real SMTP login before saving.
```bash
cyan auth smtp proj_ab12cd34 --host smtp.gmail.com --port 587 --email sender@example.com
```

### `cyan auth policy <project_id> [--require-verification/--no-require-verification] [--password-min-length N] [--max-login-attempts N] [--lockout-minutes N] [--mfa/--no-mfa]`
Update a project's security policy — password strength requirement,
whether email verification is mandatory before login, attempt-based
cooldown thresholds, and MFA. `--mfa` requires SMTP already configured
(the one-time code has to be emailed somewhere).
```bash
cyan auth policy proj_ab12cd34 --password-min-length 12 --max-login-attempts 3 --lockout-minutes 30
cyan auth policy proj_ab12cd34 --mfa
```

### `cyan auth template-show <project_id>`
Show the current templates: `email_verify`, `password_reset`, `email_change`, `mfa_login`.
```bash
cyan auth template-show proj_ab12cd34
```

### `cyan auth template-edit <project_id> <template_type> --subject "..." --body-file body.html`
Edit an email template. `template_type`: `email_verify` | `password_reset` | `email_change` | `mfa_login`.
Body file can use `{{otp}}`, `{{link}}`, `{{email}}`, `{{project_name}}`, `{{ttl_minutes}}`
(`mfa_login` has no `{{link}}` — it's code-only, entered back into your app).
```bash
cyan auth template-edit proj_ab12cd34 email_verify --subject "Confirm your account" --body-file verify.html
```

### `cyan auth users <project_id>`
List a project's registered end users — email, unique user ID (14
chars, copyable), verified status/method, disabled/locked state.
```bash
cyan auth users proj_ab12cd34
```

### `cyan auth user-disable <project_id> <user_id>` / `user-enable`
Disable or re-enable an account without deleting it. A disabled
account is blocked at login immediately.
```bash
cyan auth user-disable proj_ab12cd34 a1b2c3d4e5f601
cyan auth user-enable proj_ab12cd34 a1b2c3d4e5f601
```

### `cyan auth user-reset-password <project_id> <user_id>`
Send a password-reset email to this user (link + OTP), same as if
they'd requested it themselves.
```bash
cyan auth user-reset-password proj_ab12cd34 a1b2c3d4e5f601
```

### `cyan auth user-delete <project_id> <user_id> [--yes]`
Permanently delete an end user's account. Prompts for confirmation
unless `--yes` is passed.
```bash
cyan auth user-delete proj_ab12cd34 a1b2c3d4e5f601
```

### Security notes on the emailed links
- Every link token is **single-use** and stored only as a SHA-256 hash —
  a database leak alone can never yield a working link.
- The password-reset and email-verify links carry **only the token**, no
  API key — a leaked/forwarded link can act on that one account and
  nothing else.
- Clicking a reset-password link never resets anything by itself (a bare
  GET just shows a form); the actual change requires the POST.
- A GET click that verifies an email or confirms an email change shows
  a default success/failure page — no separate frontend needed to handle
  the click, though you can pass `base_link_url` at register/forgot-
  password/email-change time to point the link at your own app instead.

### API surface (used by your own app, not the Cyan Server admin)
Everything below takes the project's `api_key`, not an admin login —
it's what your app's signup/login forms call.
```
POST /api/authsvc/register              { api_key, email, password, base_link_url? }
POST /api/authsvc/verify-otp            { api_key, email, otp }
GET  /api/authsvc/verify-email          ?token=...                   (the emailed link — HTML page)
POST /api/authsvc/verify-email          { token }                    (JSON alternative)
POST /api/authsvc/resend-verification   { api_key, email }
POST /api/authsvc/login                 { api_key, email, password }
                                           -> { session_token, ... } normally, or
                                           -> { mfa_required: true, preauth_token } if MFA is on
POST /api/authsvc/mfa-verify            { preauth_token, otp } -> { session_token, ... }
POST /api/authsvc/forgot-password       { api_key, email, base_link_url? }
POST /api/authsvc/reset-password        { api_key, email, otp, new_password }     (OTP path)
GET  /api/authsvc/reset-password        ?token=...                   (the emailed link — HTML form)
POST /api/authsvc/email-change/request  { session_token, new_email, base_link_url? }
POST /api/authsvc/email-change/confirm-otp  { session_token, otp }
GET  /api/authsvc/confirm-email-change  ?token=...                   (the emailed link — HTML page)
```

### Admin: user management (admin-authenticated, like project management above)
```
GET    /api/authsvc/projects/{project_id}/users
DELETE /api/authsvc/projects/{project_id}/users/{user_id}
POST   /api/authsvc/projects/{project_id}/users/{user_id}/disable            { disabled }
POST   /api/authsvc/projects/{project_id}/users/{user_id}/send-password-reset
```
