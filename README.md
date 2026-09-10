# 🖥️ Cyan Server

**Turn any Windows, Linux, or macOS machine into a self-hosted personal server — with one command.**

Cyan Server is a cross-platform server-builder and management platform. It is **not an operating system** — it installs on top of whatever OS your device already runs, detects your hardware, and gives you web hosting, file storage, an application manager, and optional Cloudflare Tunnel access through one agent, one CLI, and one dashboard.

[![CI](https://github.com/nadeemmhdm/cyan-server/actions/workflows/ci.yml/badge.svg)](https://github.com/nadeemmhdm/cyan-server/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#-platform-support)
[![Version](https://img.shields.io/badge/version-0.3.0-orange.svg)](https://github.com/nadeemmhdm/cyan-server/releases)

Open source, Apache 2.0 licensed. Every feature below has been tested live against a real running agent — no mocked data, no placeholder buttons. See [What's verified](#-whats-verified) for exactly what's been proven and what still needs real-world testing.

---

## Table of contents

- [Easy setup](#-easy-setup)
- [Features](#-features)
- [Security](#-security)
- [Auto-update](#-auto-update)
- [Automatic recovery — one command brings everything back](#-automatic-recovery--one-command-brings-everything-back)
- [Remote & mobile access](#-remote--mobile-access)
- [CLI reference](#-cli-reference)
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
cyan login --username admin --password "<printed on first agent start>"
cyan setup                    # real hardware/OS/network detection
cyan web create mysite static folder ./my-site 8080
cyan web deploy mysite        # live behind Caddy in seconds
```

Dashboard: `http://localhost:7331` (or `http://<device-ip>:7331` from anywhere on your LAN — see [Remote & mobile access](#-remote--mobile-access)).

---

## ✨ Features

### Hardware & platform
- **Real hardware/OS detection** — CPU, RAM, disks, network interfaces, Docker, virtualization — on Windows, Linux, and macOS, x86_64 and ARM64
- **Platform abstraction layer** — package manager, service manager, and network manager adapters per OS (apt/dnf/pacman + systemd on Linux, winget/choco + `sc.exe` on Windows, brew + launchctl on macOS) — the core app never shells out to a hardcoded package manager
- **One CLI** (`cyan`) and **one dashboard**, served by a single agent process, for everything below

### Web hosting
- Deploy static sites, Node.js, Python, or Docker-based sites from a folder, a git repo, or a Docker image
- Real **Caddy**-backed reverse proxy — Caddyfile generated from your sites and hot-reloaded via Caddy's admin API, no manual config editing
- Per-site logs, start/stop/redeploy

### Storage server
- Configurable storage root (works the same whether it's `D:\CyanStorage`, `/mnt/storage/cyan`, or `/Users/shared/CyanStorage`)
- Upload/download, folders, quotas, and **expiring share links**
- Path-traversal protection enforced at the filesystem-resolution layer

### Application manager
- Install apps from a YAML manifest (Docker or Docker Compose)
- **Requirements are validated against your host's real, live resources** before anything installs — an app asking for more RAM than you have, or requiring Docker when it isn't installed, is rejected with the actual numbers

### Cloudflare Tunnel (optional)
- Wraps the real `cloudflared` CLI — create a tunnel, route a hostname to a local service, all from `cyan tunnel`
- Fully optional — nothing else in Cyan Server depends on it; LAN/local hosting works with zero internet exposure

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
- **From outside your LAN**: put the agent behind a **Cloudflare Tunnel** (`cyan tunnel create`, `cyan tunnel status`) and hit your chosen hostname — no port forwarding, no exposed IP.
- **Login is the same everywhere** — one admin account, one password, whether you're on the CLI, the desktop dashboard, or a phone browser. Sessions are JWT-based and expire after 12 hours.
- Don't expose port 7331 directly to the public internet without a tunnel or your own TLS in front of it — see [Security](#-security) for why.

---

## 📟 CLI reference

```
cyan login              Log in and cache a session token
cyan status             Live agent + system status
cyan setup              Run hardware/OS/network detection
cyan up                 Recover any site/app that should be running but isn't
cyan update             Check for / apply updates; --auto on|off for background mode
cyan health             Raw agent health check

cyan web list|create|deploy|stop|logs
cyan storage list|usage|mkdir|share
cyan apps list|install|start|stop
cyan tunnel status|create
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
| Windows | winget / choco | `sc.exe` | ⚠️ Real code against real tooling, not yet run on an actual Windows host |
| macOS | Homebrew | launchd | ⚠️ Real code against real tooling, not yet run on an actual Mac |

If you run this on Windows or macOS, [issues](../../issues) reporting what worked (or didn't) are genuinely useful.

---

## ✅ What's verified

Everything in the table below was exercised against a **live agent process** — real HTTP calls, real files, real subprocesses, real SQLite rows — not just written and assumed to work.

| Area | Status |
|---|---|
| Hardware/OS detection | ✅ Live on Linux |
| Single-command startup (agent + dashboard, one port) | ✅ Live |
| Web hosting (static sites) | ✅ Live — deployed, served, logged, stopped |
| Web hosting (node/python/docker) | ⚠️ Implemented, not exercised live (no sample apps on hand during build) |
| Storage (upload/list/share/quota/traversal) | ✅ Live |
| App manager (requirement validation, pass + reject cases) | ✅ Live |
| Auth (login, lockout, rate limit, audit log) | ✅ Live |
| Recovery (`cyan up`, auto-recovery on startup) | ✅ Live — including the PID-reuse regression fix |
| Auto-update (check, config) | ✅ Live |
| Cloudflare Tunnel | ⚠️ Real `cloudflared` wrapper, untestable in the build sandbox (no binary, no network route to Cloudflare) |
| Windows/macOS adapters | ⚠️ Real code, unverified on real hosts |
| One-command installer | ✅ Live — run end-to-end against this published repo from a clean directory |

---

## 🗺️ Roadmap

- [ ] Windows/macOS live verification
- [ ] Cloudflare Tunnel live verification
- [ ] Node/Python site type live verification
- [ ] Backups
- [ ] Resource-profile enforcement (Low/Balanced/Performance limits on what can be installed, beyond today's per-app RAM/storage checks)
- [ ] Multi-node rate-limit/lockout state (currently in-process only)

---

## 🤝 Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short version: this project's whole discipline is *verify it live before calling it done*, and PRs are expected to keep that up.

## 📄 License

[Apache License 2.0](LICENSE)
