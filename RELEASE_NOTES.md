# Cyan Server v0.7.2 Release Notes

**Cyan Server v0.7.2** brings a full-featured visual Website Builder to the Cyan Hub Web Dashboard (`http://localhost:7331/`), ZIP archive upload & unpacking, custom domain & tunnel connection dialogs, a first-time user welcome card with quick actions, host PostgreSQL missing-binary detection with zero-config SQLite guidance, write-only API key permission scoping, and an Admin Profile modal with secure password updating.

---

## 🌟 Major Highlights & New Features in v0.7.2

### 1. Dashboard Website Builder & File Manager (`http://localhost:7331/`)
- **Full Framework Support**: Create and host Static HTML/CSS/JS, React (Vite/CRA), Node.js (Express), Python (FastAPI/Flask), PHP, and Docker containers directly from the web UI.
- **Starter Content Generation**: Automatically creates a production-grade starter template with Outfit/Inter typography, Boxicons, dark mode, and responsive layout.
- **Direct ZIP Upload & Auto-Unpack**: Drop or upload `.zip` website bundles. Cyan Server securely unpacks archives into site directories with built-in path-traversal (Zip Slip) protection.
- **Interactive Site Management**: Table rows now include actions for Start/Stop, Open URL, Connect Domain, Connect Tunnel, Browse & Upload Files, View Logs, and Delete.
- **Custom Domain Modal**: Connect domains or subdomains with 1-click automatic Caddy reverse proxy reconfiguration and live SSL certificate reload.
- **Tunnel Connection Modal**: Connect sites to public Cloudflare (`cloudflared`) or ngrok tunnels directly from the web interface, automatically persisting route configurations for reboot auto-resume.

### 2. First-Time Dashboard Users Welcome Message
- **Welcome Banner**: A modern glassmorphism banner welcomes new administrators to the Cyan Server Hub.
- **Quick Actions**: Direct buttons for `+ Build Website`, `+ Provision Database`, `+ New Storage Bucket`, and `+ Universal API Key`.
- **Dismissible & Persistent**: Users can dismiss the banner at any time; state is saved across sessions in `localStorage`.

### 3. PostgreSQL Database Error Guidance
- **Missing Binary Detection**: When PostgreSQL is selected on a host lacking `psql`/`createdb`, the modal displays an inline warning banner instead of failing silently or throwing uncaught exceptions.
- **Zero-Config Guidance**: Explains that SQLite is built-in, serverless, and ready immediately with zero setup.
- **1-Click Switch**: Features a single-click button to switch to SQLite instantly, plus installation instructions (`winget install PostgreSQL.PostgreSQL` / `apt install postgresql`) if PostgreSQL is specifically desired.

### 4. API Key "Write Only" Permission Scoping
- **Secure Webhooks & Form Ingestion**: Introduces the `write` permission scope alongside `full` and `read`.
- **Enforced Security**: Keys with `write` permissions can execute `INSERT`/`UPDATE`/`DELETE` queries and upload bucket files, but are strictly blocked (403 Forbidden) from executing `SELECT` queries or downloading existing files.

### 5. Admin Account Profile & Password Change
- **Header Profile Trigger**: Clicking the admin avatar in the top-right opens the Admin Profile & Security modal.
- **Password Management**: Administrators can update their password via `POST /api/auth/change-password` with current password verification and bcrypt hashing.

---

# Cyan Server v0.7.1 Release Notes

**Cyan Server v0.7.1** introduces an interactive numbered CLI menu system, single-command reboot auto-resume (`cyan resume`), startup update checks with self-restart, automated modern default web page generation for newly hosted websites, and critical cross-platform Windows bug fixes.

---

## 🌟 Major Highlights & New Features

### 1. Interactive Numbered Menu CLI (`cyan` / `python cli/main.py`)
Launching `cyan` without arguments now presents a cyber-styled terminal interface with numbered navigation:
- **`[01] Host Website`**:
  - `[1] Create Website`: Prompts for website name and folder path. Automatically detects or provisions the folder, auto-generates a modern responsive `index.html` starter page (with dark mode, Outfit/Inter typography, and Boxicons), auto-allocates an open local port (8080+), registers the site, and offers instant deployment.
  - `[2] View Available Hosted Sites`: Interactive table displaying all sites, types, ports, local URLs, custom domains, and live running statuses.
  - `[3] Manage Site`: Choose a site to start, stop, connect Caddy live SSL domains, connect Cloudflare/ngrok tunnels, view live logs, or delete.
- **`[02] Database`**:
  - `[1] List Databases`: View all provisioned databases with Unique IDs (`name_4to6digits`).
  - `[2] Create Database`: Interactive database creation with SQLite/PostgreSQL engine support.
  - `[3] Run SQL Query`: Interactive SQL runner with real-time tabular output.
  - `[4] Database Info`: Inspect tables, schema, and byte sizes.
  - `[5] Delete Database`: Clean removal with trash protection or permanent delete.
- **`[03] Storage Bucket`**:
  - `[1] List Storage Buckets`: View Unique IDs, file counts, and storage sizes.
  - `[2] Create Storage Bucket`: Provision a bucket with a Unique ID and optional description.
  - `[3] View Files in Bucket`: Browse uploaded files, sizes, and MIME types.
  - `[4] Upload File to Bucket`: Upload local files directly into the bucket.
  - `[5] Delete Storage Bucket`: Remove a bucket.
- **`[04] Auto-Resume (Reboot Survival)`**:
  - Instantly restores the complete Cyan Server stack with one click or command.
- **`[00] Exit`**:
  - Clean exit from the interactive menu.

### 2. Universal Auto-Resume (`cyan resume` / Menu Option `04`)
Designed specifically for when laptops or servers are powered off or restarted:
- **Single Command Restoration**: Run `cyan resume` (or select `[04]` from the menu) at any time after booting your laptop.
- **Self-Healing Stack**:
  1. Checks if the background Agent daemon is running; automatically spawns it if offline.
  2. Recovers all previously running websites and background applications.
  3. Reloads the Caddy reverse proxy to reconnect all custom domains with valid SSL.
  4. Restores Cloudflare tunnels (`cloudflared`) and ngrok tunnels according to saved persistent route state (`tunnel_state.json`).
  5. Displays a status table verifying that every service, domain, and tunnel is online.

### 3. Startup Auto-Update Checks
- On every CLI startup, Cyan Server checks the remote git repository for new commits.
- If updates are detected, changelogs are displayed, and the tool can automatically apply the update (`git pull`) and restart the CLI in place.

### 4. Cross-Platform Windows & Security Fixes
- **Windows Command Execution**: Fixed `npm` execution in React/Node site deployment by resolving `npm.cmd` via `shutil.which()` with `shell=True` on Windows.
- **Windows CP1252 UTF-8 Safety**: Configured automatic UTF-8 stream re-encoding so box-drawing, checkmarks (`✓`), and Rich visual styling do not crash Windows terminals.
- **Background Process Detachment**: Ensured background services use `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` on Windows so child servers survive terminal closure.
- **Local CLI Authentication**: Seamlessly authenticates local CLI sessions without manual login prompts while maintaining strict JWT verification for external API requests.

---

# Cyan Server v0.7.0 Release Notes

**Cyan Server v0.7.0** introduces a modern Web Dashboard with a glassmorphism authentication gate, unified Unique ID architecture for Databases and Storage Buckets, universal developer API keys, an expanded interactive CLI, and comprehensive security hardening.

---

## 🌟 Major Highlights & New Features

### 1. Modern Cyan Server Dashboard & Authentication Gate
- **Glassmorphic Login Gate**: Full authentication gateway on the dashboard (`http://localhost:7331/`) featuring Boxicons, animated glow, show/hide password toggle, and persistent `localStorage` session management.
- **Unified Management Tabs**:
  - **Overview**: Live CPU & RAM gauges, system hardware specs, mounted storage disks, and network interfaces.
  - **Databases**: Live list of provisioned databases with Unique IDs, interactive SQL query runner, and table inspector.
  - **Storage Buckets**: Storage bucket cards with file counts, byte usage, drag-and-drop file uploader, file download, and deletion.
  - **API Keys**: Manage universal API keys with one-click copy and interactive developer quickstart snippets.
  - **Websites & Apps**: Real-time website statuses, port forwarding, and Cloudflare/ngrok tunnel monitors.

### 2. Unique ID Architecture for Databases & Storage Buckets
- Every database and storage bucket now automatically receives a human-readable, collision-resistant Unique ID:
  - **Format**: `{name}_{4_to_6_random_digits}` (e.g. `ecommerce_49182`, `media_assets_74019`).
  - Guarantees clean isolation between multiple environments or hosted applications.
  - All management functions accept either the display name or the Unique ID.

### 3. Universal API Key System & Unified Client REST API (`v1`)
- **One Key for Everything**: A single API key per user account grants authenticated access to both Databases and Storage Buckets.
- **REST Endpoints**:
  - **Databases**:
    - `GET /api/v1/database/{db_id}/status`: Inspect engine, tables, and size.
    - `POST /api/v1/database/{db_id}/query`: Execute SQL queries securely via `X-API-Key`.
    - `GET /api/v1/database/{db_id}/tables`: List database tables.
  - **Storage Buckets**:
    - `GET /api/v1/storage/{bucket_id}/files`: List all files in bucket.
    - `POST /api/v1/storage/{bucket_id}/upload`: Direct file upload via multipart/form-data.
    - `GET /api/v1/storage/{bucket_id}/download/{filename}`: Secure file stream with defensive headers.
    - `DELETE /api/v1/storage/{bucket_id}/files/{filename}`: Delete a file from bucket.

### 4. Cyan CLI Expansion
The Cyan CLI has been expanded with dedicated sub-apps and rich terminal output:
- **`cyan db` / `cyan database`**:
  - `cyan db list`: Color-coded table of all databases with Unique IDs and engine types.
  - `cyan db create <name> [--engine sqlite|postgres]`: Provision database with Unique ID.
  - `cyan db query <identifier> "<sql>"`: Run SQL queries with auto-formatted tabular results.
  - `cyan db info <identifier>`: View schema, size, and table lists.
  - `cyan db delete <identifier> [--permanent]`: Delete a database.
- **`cyan storage` / `cyan bucket`**:
  - `cyan storage list`: List all storage buckets with IDs, file counts, and size metrics.
  - `cyan storage create <name> [--desc "description"]`: Create storage bucket with Unique ID.
  - `cyan storage files <bucket_id>`: List all files in a bucket with file sizes and timestamps.
  - `cyan storage upload <bucket_id> <filepath>`: Upload local files directly to a bucket.
  - `cyan storage delete <bucket_id> [--permanent]`: Delete a storage bucket.
- **`cyan key` / `cyan apikey`**:
  - `cyan key list`: View active API keys, masked tokens, and last used timestamps.
  - `cyan key create <name> [--permissions full]`: Generate new universal API key.
  - `cyan key revoke <identifier>`: Revoke an API key.

---

## 🔒 Security Hardening

- **SQL Injection Prevention**: All query execution layers now strictly enforce parameterized bindings (`?`). Dangerous SQLite pragmas (`ATTACH`, `DETACH`, `PRAGMA WRITABLE_SCHEMA`) are blocked.
- **Path Traversal Protection**: Universal path resolution (`_safe_path()`) hardens storage against Windows backslashes, null bytes (`\0`), and drive specifiers.
- **Prohibited Executable Uploads**: Built-in extension blacklist blocks `.exe`, `.bat`, `.cmd`, `.sh`, `.php`, `.py`, `.ps1`, `.vbs`, and related executable file types.
- **Defensive HTTP Response Headers**: All file downloads and API responses enforce `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and restrictive `Content-Security-Policy`.
- **404 Console Error Elimination**: Native `/favicon.ico` and `/robots.txt` endpoints added to eliminate standard browser console noise.

---

## 💻 Cross-Platform Compatibility

- **Windows, Linux & macOS Process Model**: Unified background daemon detachment across all operating systems (`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` on Windows, `start_new_session=True` on POSIX).
- **Console UTF-8 Encoding**: Auto-reconfigured Windows standard streams to UTF-8, preventing legacy `cp1252` encoding exceptions on Unicode symbols and rich table borders.
- **Path Portability**: Universal `pathlib.Path` resolution across data roots, databases, and storage vaults.

---

## 📦 Upgrading to v0.7.0

To start the v0.7.0 agent and access the new dashboard:
```bash
# Start Cyan Server
cyan start

# Or directly via Python
python agent/main.py
```
Open [http://localhost:7331](http://localhost:7331) in your browser.
