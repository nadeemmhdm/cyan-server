# Cyan Server

Cyan Server turns an existing computer (Windows / Linux / macOS, x86_64 / ARM64)
into a configurable personal server. **It is not an operating system** — it
installs on top of whatever OS the device already runs.

## Status: Phase 1 + Phase 2, connected and tested together

Everything below was tested end-to-end against a live agent process on this
build machine (Linux/Ubuntu) — real HTTP calls, real files, real subprocess
management, real SQLite rows. Nothing here is mocked. Windows/macOS platform
adapters and the Cloudflare Tunnel module are genuine code against the real
`winget`/`brew`/`sc.exe`/`launchctl`/`cloudflared` command surfaces, but
couldn't be exercised live in this sandbox (no Windows/macOS host, no
`cloudflared` binary, no network route to Cloudflare's install domain) —
they need verification on real hosts.

### How Phase 1 and Phase 2 connect

They're not two separate codebases glued together after the fact — they
share one process and one data flow:

- **One agent, one FastAPI app.** `agent/main.py` is the same process for
  both: on startup it initializes the SQLite schema (Phase 2) right next to
  the hardware-detection endpoints (Phase 1), and mounts the Phase 2
  routers (`web`, `storage`, `apps`, `cloudflare`, `auth`) alongside the
  original `/api/system*` endpoints.
- **Phase 2 reads Phase 1's live data, not a cache of it.** The clearest
  example: `apps/manager.py::validate_requirements()` calls
  `core.detection.gather_system_report()` — the exact Phase 1 function —
  before installing any application, and rejects installs that need more
  RAM than the host actually has right now, or that need Docker when Phase
  1's detection says Docker isn't present. Tested live: an app manifest
  asking for 999999MB of RAM was rejected with the actual available RAM
  Phase 1 measured; a Docker-type app was rejected because Phase 1's
  `docker_available` check is false on this host.
- **Phase 2's process/service management reuses Phase 1's platform
  adapters.** `web/manager.py` calls `get_platform_adapters()` (Phase 1) to
  check port availability with the real `NetworkManager` before creating a
  site.
- **One CLI, one dashboard.** `cyan status`/`cyan setup` (Phase 1) and
  `cyan web`/`cyan storage`/`cyan apps`/`cyan tunnel`/`cyan update` (Phase 2)
  are subcommands of the same Typer app, talking to the same agent on
  `localhost:7331`. The dashboard's system metrics (Phase 1) and its
  Websites/Storage/Applications/Cloudflare panels (Phase 2) poll the same
  origin and share the same login token.

## What's real, module by module

| Module | Status |
|---|---|
| **Core detection** (`core/detection.py`) | Real OS/CPU/RAM/disk/network/Docker/virtualization detection |
| **Platform adapters** (`platform_impl/`) | Linux tested live (apt/systemd). Windows (winget/sc.exe) and macOS (brew/launchctl) implemented but unverified on real hosts |
| **Agent** (`agent/main.py`) | FastAPI, real endpoints, real SQLite-backed startup |
| **Auth** (`security/`) | bcrypt password hashing, JWT sessions, RBAC dependency, auto-generated admin account on first run (shown once) |
| **Database** (`core/database.py`) | Real SQLite schema (SQLAlchemy): users, websites, deployment events, storage config, share links, applications, tunnels |
| **Web Server** (`web/`) | Real Caddy-backed reverse proxy (installed and tested live — Caddyfile generation + hot reload via Caddy's admin API), site deploy for static (tested live)/node/python (subprocess-based)/docker (docker-cmd-based), start/stop/logs |
| **Storage Server** (`storage/`) | Real file manager against a configurable root: list/mkdir/delete/upload/download, quotas, expiring share links, path-traversal protection (tested live) |
| **Application Manager** (`apps/`) | YAML manifest parsing, requirement validation against live system state (tested live, both pass and reject cases), Docker/Docker Compose install+start+stop |
| **Cloudflare Tunnel** (`cloudflare/`) | Real `cloudflared` CLI wrapper, fully optional — untestable in this sandbox. Nothing else depends on it |
| **CLI** (`cli/main.py`) | `cyan login/status/setup/web/storage/apps/tunnel/update/*` — all tested live against the running agent |
| **Dashboard** (`frontend/index.html`) | Single-file HTML/JS, no build step; live system metrics plus authenticated Websites/Storage/Applications/Cloudflare panels |
| **Installer** (`installer/`) | 12-step flow from the spec, now also checks for `caddy` and prints the one-time admin credentials at the end |

## Running it locally

```bash
pip install -r requirements.txt

# Terminal 1 — agent (creates DB + admin account on first run, prints the
# one-time password to stdout)
python3 agent/main.py            # http://localhost:7331

# Terminal 2 — dashboard
cd frontend && python3 -m http.server 3000   # http://localhost:3000

# Terminal 3 — CLI
python3 cli/main.py login --username admin --password "<from agent startup log>"
python3 cli/main.py setup
python3 cli/main.py web create mysite static folder /path/to/site 8080
python3 cli/main.py web deploy mysite
python3 cli/main.py storage mkdir photos
python3 cli/main.py apps list
python3 cli/main.py update
```

Run the test suites:

```bash
python3 tests/test_detection.py   # Phase 1
python3 tests/test_phase2.py      # Phase 2 (auth, storage, app validation)
```

## Architecture

```
cyan-server/
├── core/            # detection.py (Phase 1) + database.py (Phase 2 schema)
├── platform_impl/   # OS adapters: linux/ (tested), windows/, macos/
├── security/        # bcrypt + JWT auth, RBAC dependency
├── api/             # FastAPI routers: auth, web, storage, apps, cloudflare
├── web/             # site deploy manager + Caddy reverse proxy control
├── storage/         # file manager, share links, quotas
├── apps/            # manifest-based app installer, requirement validation
├── cloudflare/       # cloudflared CLI wrapper (optional)
├── agent/           # the one process that ties all of the above together
├── cli/             # Typer CLI — talks to the agent over HTTP
├── frontend/         # dashboard (static HTML/JS)
├── installer/         # install.sh (Linux/macOS), install.ps1 (Windows)
├── tests/             # test_detection.py, test_phase2.py
├── .github/workflows/ # CI: runs both test suites on every push
└── requirements.txt
```

Note: the package is named `platform_impl/`, not `platform/`, to avoid
shadowing Python's standard library `platform` module once the repo root is
on `sys.path` — the spec's diagram uses `platform/`; this is a naming
adjustment for correctness, not a structural deviation.

## Security notes

- Every mutating Phase 2 endpoint (`/api/web`, `/api/storage`, `/api/apps`,
  `/api/cloudflare`, except the public `available` check and public share
  links) requires a valid JWT — tested live: unauthenticated requests get a
  real `401`, not a silent bypass.
- Passwords are hashed with bcrypt directly (not passlib — passlib 1.7.4 is
  incompatible with bcrypt ≥4.1 due to an upstream bug; this was hit and
  fixed during development).
- Storage path traversal is rejected at the filesystem-resolution layer,
  not just by string matching — tested live against `../../etc`.
- `PackageManager.install()` is only ever called after `plan_install()` has
  produced a plan the caller must show the user — nothing installs
  silently.
- The agent has no built-in TLS/rate-limiting yet; it's designed for
  localhost/LAN use, with Cloudflare Tunnel as the sanctioned path to the
  internet. Don't expose port 7331 directly to the internet without adding
  TLS and rate limiting first.

## Known gaps / next steps

1. **Windows/macOS verification** — the adapters and installer are written
   against real tooling but need a run on an actual Windows and macOS
   machine.
2. **Cloudflare Tunnel** — needs `cloudflared` installed and a real
   Cloudflare account to verify `login`/`create_tunnel`/`add_hostname`.
3. **Node/Python site types** in `web/manager.py` are implemented but only
   the `static` path was exercised live here.
4. **Backups** (spec section 19) and **monitoring history** (section 18
   beyond live polling) are not built yet.
5. **Resource-profile enforcement** (Low/Balanced/Performance limiting what
   can be installed) is computed by Phase 1 but not yet wired into
   Phase 2's install path beyond the per-app RAM/storage checks.
