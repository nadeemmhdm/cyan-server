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
| 0.11.x  | ✅ |
| 0.6.x – 0.10.x | ✅ (upgrade recommended — `cyan update`) |
| < 0.6   | ❌ (upgrade — `cyan update`) |

## Current security posture (v0.11.0)

- Passwords: bcrypt-hashed, never stored or logged in plaintext.
- **Auth Service** (project-scoped end-user authentication): passwords
  follow the same bcrypt hashing and a project-configurable strength
  policy (length + character classes + common-password denylist); SMTP
  app passwords for sending verification emails are Fernet-encrypted at
  rest and verified with a real login attempt before being saved;
  failed-login lockout is database-backed and progressive (each repeat
  lockout roughly doubles the cooldown, capped at 24h) rather than a
  simple fixed window; session tokens use a JWT secret kept entirely
  separate from the admin dashboard's, so one can never be replayed as
  the other; login responses are shaped to avoid confirming whether an
  email is registered.
  - Verification/reset/email-change **link tokens are single-use and
    stored only as a SHA-256 hash** — a database leak alone can't yield
    a working link. The password-reset and email-change links carry
    only the token, no API key, so a leaked link can act on exactly
    one account.
  - Optional **email-OTP multi-factor authentication** per project — a
    successful password check returns a short-lived pre-auth token
    (5 min) instead of a session; the real session is only issued after
    the emailed code is also verified. Requires SMTP to already be
    configured.
  - Email changes require an active session and are confirmed at the
    **new** address (link or OTP) before taking effect; a taken email
    can't be reused across accounts in the same project.
  - Row-level isolation between projects is enforced at the application
    layer (SQLite has no native RLS): every end-user lookup goes
    through one centralized, always project-scoped helper, so a valid
    API key or session token for project A can never resolve or act on
    project B's rows, even with a matching email address — covered by
    an explicit cross-project test.
- Optional TOTP two-factor authentication per user, on top of the
  password/JWT flow below.
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
- Load-balanced sites (`--replicas > 1`) run multiple real backend
  processes on consecutive ports on the same host — they share that
  host's resources and are not a substitute for multi-host redundancy.
  All replicas of a site trust the same source/env vars as a single
  instance would; there's no per-replica isolation.
- Windows has been live-verified by a contributor as of v0.5.1 (6 real
  bugs found and fixed — see the changelog). macOS has not yet had an
  equivalent real-hardware pass; treat the macOS platform adapter as
  unverified until it does.
