# Contributing to Cyan Server

Thanks for considering contributing. This project favors small, verified
changes over large speculative ones — see the ground rule below.

## Ground rule: no unverified features

This codebase was built with a specific discipline: **every feature is
tested live before it's considered done — no mocked data, no
placeholder buttons, no "should work" without a real run to back it up.**
Please keep that up:

- New endpoints: hit them with `curl` (or the CLI) against a running
  agent and show the real response, not just that the code compiles.
- New CLI commands: run them against a live agent.
- Anything touching processes, ports, or the filesystem: prefer a check
  that observes real state (e.g. "is something listening on this port")
  over one that trusts stored state (e.g. "the DB says it's running") —
  see `web/manager.py::_is_actually_running` for why: PIDs get reused,
  especially fast inside containers, so a stored PID can silently start
  pointing at an unrelated live process.

## Getting set up

```bash
git clone https://github.com/nadeemmhdm/cyan-server.git
cd cyan-server
pip install -r requirements.txt

python3 agent/main.py          # terminal 1 — prints the one-time admin password
cd frontend && python3 -m http.server 3000   # terminal 2
python3 cli/main.py login --username admin --password "<from agent output>"
```

## Running tests

```bash
python3 tests/test_detection.py   # hardware/OS detection
python3 tests/test_services.py    # auth, storage, app validation
python3 tests/test_recovery.py    # crash/reboot recovery
python3 tests/test_recovery.py    # crash/reboot recovery
```

CI (`.github/workflows/ci.yml`) runs all three on every push.

## Where things live

See the Architecture section in `README.md` for the module layout. In
short: `core/` and `platform_impl/` handle hardware/OS detection,
`web/`, `storage/`, `apps/`, `cloudflare/`, `security/` are the service
modules, and `agent/main.py` is the one process that wires everything
together (API, dashboard, and every module) — see that file's
`_startup()` for the actual connection points.

## Pull requests

- One logical change per PR.
- Include the command(s) you ran to verify it, and their real output, in
  the PR description.
- Update `README.md`'s feature table if you're changing what's
  real/verified vs. planned.
