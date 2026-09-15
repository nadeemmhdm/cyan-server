# 🖥️ Cyan Server

**Turn any Windows, Linux, or macOS machine into a self-hosted personal server — with one command.**

Cyan Server is a cross-platform server-builder and management platform. It is **not an operating system** — it installs on top of whatever OS your device already runs, detects your hardware, and gives you web hosting, file storage, SQL databases, an application manager, and worldwide access via Cloudflare Tunnel or ngrok, through one agent, one CLI, and one dashboard.

[![CI](https://github.com/nadeemmhdm/cyan-server/actions/workflows/ci.yml/badge.svg)](https://github.com/nadeemmhdm/cyan-server/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#-platform-support)
[![Version](https://img.shields.io/badge/version-0.12.0-orange.svg)](https://github.com/nadeemmhdm/cyan-server/releases)

Open source, Apache 2.0 licensed. Every feature below has been tested live against a real running agent — no mocked data, no placeholder buttons. See [What's verified](#-whats-verified) for exactly what's been proven and what still needs real-world testing.

---

## Table of contents

- [Easy setup](#-easy-setup)
- [Features](#-features)
- [Security](#-security)
- [Auto-update](#-auto-update)
- [Automatic recovery — one command brings everything back](#-automatic-recovery--one-command-brings-everything-back)
- [Remote & mobile access](#-remote--mobile-access)
- [CLI reference](#-cli-reference) — full command-by-command reference with examples: [docs/COMMANDS.md](docs/COMMANDS.md)
- [Architecture](#-architecture)
- [Platform support](#-platform-support)
- [What's verified](#-whats-verified)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Easy setup

One command installs everything and starts a single process that serves both the API and the dashboard — no separate services to wire up.

**Linux / macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/nadeemmhdm/cyan-server/main/installer/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/nadeemmhdm/cyan-server/main/installer/install.ps1 | iex
```

The installer detects your OS/architecture, checks dependencies (Python, git, Caddy), clones the repo, creates a virtualenv, starts the agent, and prints a one-time admin password. That's it — open the dashboard and you're in.

Prefer to run it manually, or already have the repo?

```bash
pip install -r requirements.txt
python3 agent/main.py     # ONE command — API + dashboard both come up on :7331
```

Then from the CLI:

```bash
cyan                            # Launches the interactive cyber numbered menu:
                                #   [01] Host Website
                                #   [02] Database
                                #   [03] Storage Bucket
                                #   [04] Auto-Resume (Reboot Survival)
                                #   [00] Exit

cyan resume                     # Single-command reboot survival: restores agent daemon,
                                # all hosted websites, Caddy SSL domains, and public tunnels!
```

Or use direct subcommands:
```bash
cyan setup                      # real hardware/OS/network detection
cyan web create mysite static folder ./my-site 8080
cyan web deploy mysite          # live behind Caddy in seconds
```

Dashboard: `http://localhost:7331` (or `http://<device-ip>:7331` from anywhere on your LAN — see [Remote & mobile access](#-remote--mobile-access)).

---

## ✨ Features

### Hardware & platform
- **Real hardware/OS detection** — CPU, RAM, disks, network interfaces, Docker, virtualization — on Windows, Linux, and macOS, x86_64 and ARM64
- **Platform abstraction layer** — package manager, service manager, and network manager adapters per OS (apt/dnf/pacman + systemd on Linux, winget/choco + `sc.exe` on Windows, brew + launchctl on macOS) — the core app never shells out to a hardcoded package manager
- **One CLI** (`cyan`) and **one dashboard**, served by a single agent process, for everything below

### Auth Service — email+password auth as a feature
- Add real user authentication to your own app or site: create a **project**, get a **project ID + API key**, point your signup/login forms at it
- Email verification via both a link and a 6-digit OTP; password reset the same way — every link token is **single-use, stored only as a hash**, and (for reset/email-change) carries no API key, so a leaked link can only act on that one account
- Optional **email-OTP multi-factor authentication** per project, and a session-gated **email change** flow confirmed at the new address before it takes effect
- Default success/failure landing pages for emailed links out of the box — no separate frontend required to handle a click
- SMTP is collected only when you configure this feature, and is **verified with a real login attempt** before being saved — nothing sends until that check passes
- Real password policy (length, character classes, common-password denylist), real bcrypt hashing, and a **database-backed progressive lockout** (each repeat lockout doubles the cooldown) — not just an in-memory rate limit that resets on restart
- **Row-level isolation between projects**, enforced at the application layer through one centralized, always-scoped lookup — a project's API key or session token can never resolve another project's rows
- Editable per-project email templates (verify, reset, email-change, MFA code)
- `cyan auth project-create`, `cyan auth smtp`, `cyan auth policy`, `cyan auth template-edit` — see [docs/COMMANDS.md](docs/COMMANDS.md#auth-service)

### Web hosting
- Deploy static sites, Node.js, Python, PHP, or React (build + serve), or Docker-based sites from a folder, a git repo, or a Docker image
- Real **Caddy**-backed reverse proxy — Caddyfile generated from your sites and hot-reloaded via Caddy's admin API, no manual config editing
- **Load balancing** — `cyan web create ... --replicas N --lb-policy <policy>` runs N real backend instances of a site behind Caddy, distributed with `round_robin`, `least_conn`, `random`, or `ip_hash`. Stopping the site tears down every replica cleanly
- **Site file manager** — list, read, edit, upload, and delete files directly inside a deployed site's folder, without a full redeploy. Editing a static/React file takes effect on the next request — no restart needed
- **Domain and subdomain connection** — `cyan web domain <site> <hostname>` connects (or changes, or clears) a hostname live, no redeploy needed; subdomains work exactly the same way as root domains
- Per-site logs, start/stop/redeploy
- **Trash/recycle bin** — deleting a site moves it (source + domain + config) to a 30-day trash instead of destroying it; `cyan trash restore <id>` brings it back running, `--permanent` skips trash for good

### Storage server
- Configurable storage root (works the same whether it's `D:\CyanStorage`, `/mnt/storage/cyan`, or `/Users/shared/CyanStorage`)
- Upload/download, folders, quotas, and **expiring share links**
- Path-traversal protection enforced at the filesystem-resolution layer
- **Trash / recycle bin** — deletions aren't immediate. Deleted files move to a 30-day trash, restorable with one command (`cyan trash restore <id>`), auto-purged in the background after 30 days, or emptied on demand (`--permanent` skips trash entirely for anything you genuinely want gone right away)

### Backup & restore
- **Point-in-time snapshots** — `cyan backup create` tars up the full config database (via SQLite's own backup API for a consistent snapshot, not a raw file copy that could catch a torn write), the Caddy config, every deployed site's source, and every managed SQLite database. Storage files are opt-in (`--include-storage`) since they can be large
- **Automatic backups** — on by default, configurable interval and retention (`cyan backup config`)
- **Restore** — `cyan backup restore <file>` stops the agent, extracts the archive, and restarts (automatic recovery brings sites back up). Your pre-restore state is moved aside, not deleted, so a bad restore is itself undoable
- Archive extraction is tarbomb/path-traversal-safe — every member is validated before anything touches disk

### Database server
- **SQL database provisioning** — `cyan db create <name>` creates a real, isolated SQLite database file (no external service needed); Postgres is supported the same way if it's installed on the host
- Run management queries directly — `cyan db query <name> "<sql>"` — admin-only, same auth gate as everything destructive
- **Live status** — real file size, real table list, real per-table row counts, not cached
- Trash-aware deletion for SQLite databases (30-day restore, same as storage/websites); Postgres drops are permanent (there's no meaningful "trash" for a live SQL server without pg_dump-based snapshotting, which isn't built yet)

### Application manager
- Install apps from a YAML manifest (Docker or Docker Compose)
- **Requirements are validated against your host's real, live resources** before anything installs — an app asking for more RAM than you have, or requiring Docker when it isn't installed, is rejected with the actual numbers

### Worldwide access via tunnels
- **Two tunnel providers**: Cloudflare Tunnel (custom domains, needs a Cloudflare account) and ngrok (instant public URL, no domain needed) — `cyan tunnel status` shows what's installed
- **`cyan tunnel connect <site> ...`** — the actual "local site, worldwide access" step in one command: looks up your deployed site's real local port automatically, so you never construct a `local_service` URL by hand
- **Multiple domains per tunnel** — run `cyan tunnel connect` again with a different `--hostname`/site and the same `--tunnel-name`: one Cloudflare tunnel serves any number of domains, each routed to its own site's real port via a generated `cloudflared` ingress config (not just a DNS record with nowhere to route). `cyan tunnel domains` lists everything connected; `cyan tunnel disconnect-domain` drops one
- Once a site has a connected domain (`cyan web domain`) *and* a tunnel route to that same hostname, it's reachable from any device, anywhere, with no port-forwarding and no public IP
- Fully optional — nothing else in Cyan Server depends on either provider; LAN/local hosting works with zero internet exposure

---

## 🔒 Security

Security isn't bolted on — it's enforced at the framework level:

| Control | Implementation |
|---|---|
| **Password storage** | bcrypt, direct (never plaintext, never logged) |
| **Sessions** | JWT, 12-hour expiry, signed with a per-install secret (`0600` permissions) |
| **Brute-force protection** | IP-based sliding-window rate limit (10 req/min) **+** per-username lockout (5 failed attempts → 5-minute lockout) on every login attempt |
| **Audit trail** | Every login success/failure/lockout logged, queryable via `/api/auth/audit-log` (admin-only) |
| **Authorization** | Every mutating endpoint requires a valid JWT — tested live: unauthenticated requests get a real `401`, not a silent bypass |
| **Path traversal** | Storage paths resolved and validated against the real root on every call, not string-matched |
| **Package installs** | Shown to the user as a plan *before* execution — nothing installs silently, ever |
| **Security patches** | Flagged commits (`[security]`/`CVE-`) auto-apply even with background auto-apply turned off — see [Auto-update](#-auto-update) |
| **Response headers** | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` on every response |
| **Privilege separation** | Never runs as root/admin by default; elevated operations go through platform-specific adapters, not raw shell strings |

Full policy and current known limitations: [SECURITY.md](SECURITY.md).

---

## 🔄 Auto-update

`cyan update` follows the same "check first, act on confirmation" pattern as package installs — plus an optional background mode:

```bash
cyan update                 # check only — shows what's available, changes nothing
cyan update --apply         # check, then apply (fast-forward only, never rewrites history)
cyan update --auto on       # enable background auto-check + auto-apply
cyan update --auto off      # background checks continue; auto-apply turned off (default)
```

- A background thread checks your configured git remote on an interval (default: 60 min)
- **Auto-*checking*** is on by default; **auto-*applying*** is off by default — you decide when updates land unless you explicitly opt in
- **Exception: security fixes apply automatically regardless of the auto-apply setting.** A pending commit whose message contains `[security]` or a `CVE-` reference is treated as urgent and applied even if you've turned auto-apply off — `cyan update` also flags this clearly before it happens, so you're never surprised, but the patch doesn't wait on your preference the way a routine update does
- Updates only ever apply via `git merge --ff-only` — never a force-push, never a history rewrite
- Current status (last check time, result, config) is always available at `GET /api/update/config`

---

## 🔁 Automatic recovery — one command brings everything back

If the agent restarts (reboot, crash, time offline), your sites and apps don't just stay down:

```bash
cyan up
```

This re-deploys anything that was running before the agent last stopped — and it runs **automatically on every agent startup** too, so a reboot alone is often enough. It's idempotent: running it against already-running services just confirms they're up and does nothing else.

Under the hood this checks *real* liveness — whether something is actually listening on the site's port — rather than trusting a stored PID. (PIDs get reused, especially fast in containers; a naive "does this PID exist" check can report a dead site as running because an unrelated process now holds that number. This was caught and fixed with a regression test: `tests/test_recovery.py`.)

---

## 📱 Remote & mobile access

The dashboard is a single responsive page — no app to install, works in any mobile browser.

- **On your LAN**: open `http://<device-ip>:7331` from your phone or laptop and log in with your Cyan Server username and password (same account `cyan login` uses). Find your device's IP with `cyan setup` (it's in the Network section of the output).
- **From outside your LAN**: put a site behind a **Cloudflare Tunnel or ngrok** (`cyan tunnel connect <site> --hostname ... --provider cloudflare|ngrok`) and hit your chosen hostname or the generated URL — no port forwarding, no exposed IP.
- **Login is the same everywhere** — one admin account, one password, whether you're on the CLI, the desktop dashboard, or a phone browser. Sessions are JWT-based and expire after 12 hours.
- Don't expose port 7331 directly to the public internet without a tunnel or your own TLS in front of it — see [Security](#-security) for why.

---

## 📟 CLI reference

Full reference with a real, verified usage example for every single
command: **[docs/COMMANDS.md](docs/COMMANDS.md)**. Quick overview:

```
cyan start              Start the agent (API + dashboard, one process)
cyan stop               Stop the running agent
cyan restart            Restart in one command (recovery brings services back up)
cyan uninstall           Remove Cyan Server — asks for typed confirmation first
cyan login              Log in (password only — username is always admin) and cache a session token
cyan status             Live agent + system status
cyan setup              Run hardware/OS/network detection
cyan up                 Recover any site/app that should be running but isn't
cyan update             Check for / apply updates; --auto on|off for background mode
cyan health             Raw agent health check

cyan web list|create|deploy|stop|logs|domain|delete|files|edit|rm-file
cyan storage list|usage|mkdir|share|delete
cyan trash list|restore|empty
cyan backup create|list|restore|config
cyan db list|create|status|query|delete
cyan apps list|install|start|stop
cyan tunnel status|create|connect|url
```

Custom admin credentials at first run (instead of the auto-generated password):
```bash
CYAN_ADMIN_USER=myname CYAN_ADMIN_PASSWORD=mypassword cyan start
```

---

## 🏗️ Architecture

```
cyan-server/
├── core/            # detection.py (hardware/OS), database.py (schema), update.py, version.py
├── platform_impl/   # OS adapters: linux/ (tested live), windows/, macos/
├── security/        # bcrypt + JWT auth, rate limiting/lockout, security headers, RBAC
├── api/             # FastAPI routers: auth, web, storage, apps, cloudflare
├── web/             # site deploy manager + Caddy reverse proxy control
├── storage/         # file manager, share links, quotas
├── apps/            # manifest-based app installer, requirement validation
├── cloudflare/      # cloudflared CLI wrapper (optional)
├── agent/           # the one process that serves the API AND the dashboard
├── cli/             # Typer CLI — talks to the agent over HTTP
├── frontend/        # dashboard (static HTML/JS, no build step, mobile-responsive)
├── installer/       # install.sh (Linux/macOS), install.ps1 (Windows)
├── tests/           # test_detection.py, test_phase2.py, test_recovery.py
└── .github/workflows/ci.yml
```

One agent process (`agent/main.py`) owns hardware detection, every service module, and the dashboard itself — they're not separate services glued together. The clearest example of that wiring: the Application Manager validates install requirements by calling the *exact same* system-detection function the dashboard uses to show your live CPU/RAM — so "not enough RAM" and "Docker not available" errors reflect your host's real state at that moment, not a cached assumption.

> **Note:** the package is `platform_impl/`, not `platform/` — a top-level `platform/` package would shadow Python's standard library `platform` module once the repo root is on `sys.path`, which would break hardware detection itself.

---

## 💻 Platform support

| OS | Package manager | Service manager | Status |
|---|---|---|---|
| Linux | apt / dnf / yum / pacman / zypper | systemd | ✅ Tested live (this repo's CI runs on Ubuntu) |
| Windows | winget / choco | `sc.exe` | ✅ **Tested live on real Windows** by a contributor — 6 real bugs found and fixed (Caddy trust-store dialog hang, console encoding crash, stale-path bug affecting 9 modules, file-locking on redeploy, config-wipe on restart) — see commit history for the full list |
| macOS | Homebrew | launchd | ⚠️ Real code against real tooling, not yet run on an actual Mac |

If you run this on macOS, [issues](../../issues) reporting what worked (or didn't) are genuinely useful — Windows already got a real pass.

---

## ✅ What's verified

Everything in the table below was exercised against a **live agent process** — real HTTP calls, real files, real subprocesses, real SQLite rows — not just written and assumed to work.

| Area | Status |
|---|---|
| Hardware/OS detection | ✅ Live on Linux |
| Single-command startup (agent + dashboard, one port) | ✅ Live |
| Web hosting (static sites) | ✅ Live — deployed, served, logged, stopped, and redeployed-while-running (Windows file-lock case) |
| Web hosting (react) | ✅ Live — real npm install + npm run build + serve the real output directory |
| Web hosting (node/python/docker) | ⚠️ Implemented, not exercised live (no sample apps on hand during build) |
| Web hosting (php) | ⚠️ Real code (PHP's built-in server), unverified — same broken package mirror that blocked Postgres also blocked php-cli in this sandbox |
| Storage (upload/list/share/quota/traversal) | ✅ Live |
| App manager (requirement validation, pass + reject cases) | ✅ Live |
| Auth (login, lockout, rate limit, audit log) | ✅ Live |
| Recovery (`cyan up`, auto-recovery on startup) | ✅ Live — including the PID-reuse regression fix |
| Trash / recycle bin (delete → restore, permanent delete, expiry purge) | ✅ Live — storage AND websites now, full round trip tested for both (including a real domain/subdomain-preservation check on website restore) |
| Domain/subdomain connection (`cyan web domain`) | ✅ Live — verified against the actual generated Caddyfile, tested with both a root domain and a subdomain |
| Site file manager (`cyan web files/edit/rm-file`) | ✅ Live — edited a live static site's file through the CLI and confirmed the running server immediately served the new content with zero redeploy; cross-site path-traversal isolation verified |
| Database manager (SQLite: create, query, status, delete/restore) | ✅ Live — full round trip including a real CREATE TABLE + INSERT + data-integrity check across delete/restore |
| Database manager (Postgres) | ⚠️ Real code against the real `psql`/`createdb`/`dropdb` surface, unverified — the build sandbox's package mirror returned 404s for every Postgres package at build time |
| Backup & restore | ✅ Live — full disaster-recovery test: real site + real database created, explicit backup taken, **actual `cyan backup restore` run** (stops agent, extracts, restarts), site auto-redeployed and serving again, database row data intact, pre-restore state genuinely preserved on disk (not deleted). A stale-connection-pool bug was caught and fixed during this: `attempt to write a readonly database` after a second restore in the same process, fixed by disposing the SQLAlchemy engine's pool as part of restore |
| Auto-update (check, config) | ✅ Live |
| Cloudflare Tunnel | ⚠️ Real `cloudflared` wrapper, untestable in the build sandbox (no binary, no network route to Cloudflare) |
| ngrok Tunnel | ⚠️ Real code against ngrok's CLI/local API, untestable in this sandbox — the npm-based installer's binary download isn't reachable |
| Tunnel↔site connection (`cyan tunnel connect`) | ✅ Live — real site-port lookup against a deployed site, correct error ordering (missing site caught before provider check), honest provider-unavailable errors for both providers |
| Windows/macOS adapters | ✅ **Windows: live-verified by a contributor**, 6 real bugs found and fixed (all documented in commit history). ⚠️ macOS: real code, unverified on real hosts |
| One-command installer | ✅ Live — run end-to-end against this published repo from a clean directory |

---

## 🗺️ Roadmap

- [ ] PHP live verification (real code, needs a host where the package actually installs)
- [ ] Backup to remote destinations (S3-compatible, SFTP, network share — currently local filesystem only)
- [ ] Postgres live verification (real code, needs a host where the package actually installs)
- [ ] Postgres trash/snapshot-based delete (currently always permanent)
- [ ] macOS live verification
- [ ] Cloudflare Tunnel live verification
- [ ] ngrok live verification
- [ ] Node/Python site type live verification
- [ ] Backups
- [ ] Resource-profile enforcement (Low/Balanced/Performance limits on what can be installed, beyond today's per-app RAM/storage checks)
- [ ] Multi-node rate-limit/lockout state (currently in-process only)

---

## 🤝 Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short version: this project's whole discipline is *verify it live before calling it done*, and PRs are expected to keep that up.

## 📄 License

[Apache License 2.0](LICENSE)
