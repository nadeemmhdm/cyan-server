# Security Policy

Cyan Server manages web hosting, file storage, SQL databases, and
application deployment on a real host — security issues here can mean
real compromise. Please report responsibly.

## Reporting a Vulnerability

Do **not** open a public GitHub issue for security vulnerabilities.

Instead, open a [GitHub Security Advisory](../../security/advisories/new)
on this repository (private by default) with:

- A description of the vulnerability and its impact
- Steps to reproduce
- Affected version(s)

We'll acknowledge reports and work with you on a fix and coordinated
disclosure timeline.

## Supported Versions

| Version | Supported |
|---|---|
| 0.5.x   | ✅ |
| < 0.5   | ❌ (upgrade — `cyan update`) |

## Current security posture (v0.5.1)

- Passwords: bcrypt-hashed, never stored or logged in plaintext.
- Sessions: JWT, 12-hour expiry, signed with a per-install secret generated
  on first run (`~/.cyan-server/.cyan_secret`, `0600` permissions).
- Login endpoint: IP-based sliding-window rate limiting (10 req/min) and
  per-username lockout (5 failed attempts → 5-minute lockout), both logged
  to an audit trail (`/api/auth/audit-log`, admin-only).
- Every mutating API endpoint requires a valid JWT; unauthenticated
  requests get a real `401`. Admin-only operations (audit log, database
  query execution, backup creation/config) require the `admin` role
  specifically, not just any authenticated session.
- Storage: path-traversal protected at the filesystem-resolution layer,
  not by string matching.
- Backup restore: archive extraction validates every member against
  path-traversal/tarbomb patterns before anything touches disk, and is
  deliberately CLI-only (no API endpoint) since it requires stopping the
  agent first.
- Package installs: shown to the user as a plan *before* execution —
  nothing installs silently.
- Response headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options:
  DENY`, `Referrer-Policy: no-referrer` on every response.
- Security-flagged updates (commit messages containing `[security]` or a
  `CVE-` reference) auto-apply even when background auto-apply is
  otherwise turned off — see the README's Auto-update section.

## Known limitations (be aware of these before exposing to the internet)

- The agent has **no built-in TLS** — it's designed for localhost/LAN use.
  Use Cloudflare Tunnel (or your own reverse proxy with TLS) before
  exposing it beyond your LAN.
- Rate limiting and lockout state are in-memory per agent process — they
  reset on restart and don't share state across multiple agent instances.
- Auto-update (`cyan update --auto on`) only ever fast-forward merges from
  `origin` — it will not run arbitrary code from a non-fast-forward
  history, but you're trusting whatever is in the git remote you've
  configured. Only point `CYAN_REPO_URL` at a remote you trust.
- Postgres database drops (via the Database Manager) are always
  permanent — there's no trash/snapshot step for a live SQL database yet
  (SQLite databases do go through the same 30-day trash as storage/sites).
- Windows has been live-verified by a contributor as of v0.5.1 (6 real
  bugs found and fixed — see the changelog). macOS has not yet had an
  equivalent real-hardware pass; treat the macOS platform adapter as
  unverified until it does.
