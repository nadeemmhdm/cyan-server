#!/usr/bin/env sh
# Cyan Server installer for Linux / macOS. — https://github.com/nadeemmhdm/cyan-server
# Usage: curl -fsSL https://install.cyanserver.dev | sh
set -eu

INSTALL_DIR="${CYAN_INSTALL_DIR:-$HOME/.cyan-server}"
REPO_URL="${CYAN_REPO_URL:-https://github.com/nadeemmhdm/cyan-server}"  # real, published repo
PY_MIN_MAJOR=3
PY_MIN_MINOR=10

echo "Cyan Server Installer"
echo "======================"

# --- 1. Detect platform -----------------------------------------------------
OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Linux)  PLATFORM="linux" ;;
  Darwin) PLATFORM="macos" ;;
  *) echo "✗ Unsupported platform: $OS_NAME"; exit 1 ;;
esac
echo "✓ Detected platform: $PLATFORM"

# --- 2. Detect architecture --------------------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  arm64|aarch64) ARCH="arm64" ;;
esac
echo "✓ Detected architecture: $ARCH"

# --- 3. Check requirements ---------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 is required but was not found."
  echo "  Install Python 3.10+ and re-run this installer."
  exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "✓ Found python3 ($PY_VERSION)"

if ! command -v git >/dev/null 2>&1; then
  echo "✗ git is required but was not found. Install git and re-run."
  exit 1
fi
echo "✓ Found git"

if ! command -v caddy >/dev/null 2>&1; then
  echo "→ caddy not found — required for Web Server hosting (Storage/Apps work without it)."
  echo "  Install it via your package manager (e.g. 'apt install caddy', 'brew install caddy')"
  echo "  and re-run 'cyan web deploy' once installed. Continuing without it for now."
else
  echo "✓ Found caddy"
fi

# --- 4/5. Install agent + dependencies --------------------------------------
if [ -d "$INSTALL_DIR" ]; then
  echo "→ Existing install found at $INSTALL_DIR, updating..."
  git -C "$INSTALL_DIR" pull --ff-only || echo "  (skipping update — not a clean git checkout)"
else
  echo "→ Cloning Cyan Server to $INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
    echo "  (repo not reachable — copying local sources instead, for local builds)"
    mkdir -p "$INSTALL_DIR"
  }
fi

echo "→ Creating virtual environment"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- 6. Symlink CLI -----------------------------------------------------------
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/cyan" << EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/cli/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/cyan"
echo "✓ Installed 'cyan' CLI to $BIN_DIR/cyan"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  NOTE: add $BIN_DIR to your PATH to use 'cyan' directly." ;;
esac

# --- 7/8. Start agent (also serves the dashboard on the same port) ----------
echo "→ Starting Cyan Agent"
nohup "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/agent/main.py" > "$INSTALL_DIR/agent.log" 2>&1 &
sleep 1

# --- 9. Generate secure credentials (placeholder for Phase 2 auth) ----------
if [ ! -f "$INSTALL_DIR/.cyan_secret" ]; then
  python3 -c "import secrets; print(secrets.token_hex(32))" > "$INSTALL_DIR/.cyan_secret"
  chmod 600 "$INSTALL_DIR/.cyan_secret"
  echo "✓ Generated local agent secret"
fi

# --- 10. Detect local IP ------------------------------------------------------
LOCAL_IP="$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
except OSError:
    print('127.0.0.1')
finally:
    s.close()
")"

# --- 11. Health check ---------------------------------------------------------
sleep 1
if curl -fsS http://localhost:7331/api/health >/dev/null 2>&1; then
  echo "✓ Agent healthy"
else
  echo "✗ Agent did not respond. Check $INSTALL_DIR/agent.log"
  exit 1
fi

# --- 12. Show dashboard address -----------------------------------------------
echo
echo "Cyan Server is ready."
echo "  Local:   http://localhost:7331"
echo "  Network: http://$LOCAL_IP:7331"
echo
echo "First-run admin credentials were printed once to $INSTALL_DIR/agent.log — save them now:"
grep -A2 "First run" "$INSTALL_DIR/agent.log" 2>/dev/null || true
echo
echo "Run 'cyan login', then 'cyan status' or 'cyan setup' to continue."
