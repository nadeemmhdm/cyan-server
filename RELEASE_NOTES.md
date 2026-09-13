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
