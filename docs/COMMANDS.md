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
