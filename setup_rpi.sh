#!/usr/bin/env bash
# =============================================================================
#  Threat Landscape Pipeline — Raspberry Pi Setup Script
#  Barry Cheevers | barrycheevers.co.uk
#
#  Run this script once on a fresh Raspberry Pi OS installation.
#  It installs system dependencies, sets up Python, creates the virtual
#  environment, configures credentials, sets up the cron job, and optionally
#  runs a first build.
#
#  Usage:
#    chmod +x setup_rpi.sh
#    ./setup_rpi.sh
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }
section() { echo -e "\n${BOLD}${CYAN}━━━  $*  ━━━${RESET}"; }

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/logs"
REQUIRED_PYTHON_MINOR=11   # 3.11+

# =============================================================================
#  STEP 1 — Preflight checks
# =============================================================================
section "Step 1: Preflight checks"

# Must not run as root
if [[ "$EUID" -eq 0 ]]; then
    die "Do not run this script as root. Run as your normal Pi user."
fi

# Confirm we are in the project directory
if [[ ! -f "$PROJECT_DIR/requirements.txt" ]]; then
    die "Could not find requirements.txt. Run this script from the ThreatLandscape project root."
fi

success "Running as $(whoami) in $PROJECT_DIR"

# =============================================================================
#  STEP 2 — System packages
# =============================================================================
section "Step 2: Installing system packages"

info "Updating package lists…"
sudo apt-get update -qq

# Detect best available Python 3.11+
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" &>/dev/null; then
        MINOR=$("$candidate" -c 'import sys; print(sys.version_info.minor)')
        if [[ "$MINOR" -ge "$REQUIRED_PYTHON_MINOR" ]]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    info "Python 3.11+ not found — installing python3.11…"
    sudo apt-get install -y python3.11 python3.11-venv python3.11-pip
    PYTHON_BIN="python3.11"
fi

PYTHON_VERSION=$("$PYTHON_BIN" --version)
success "Using $PYTHON_VERSION ($PYTHON_BIN)"

# Additional system libraries that some pip packages need at build time
info "Installing system libraries (libxml2, libxslt, libffi)…"
sudo apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    libffi-dev \
    libssl-dev \
    openssh-client \
    curl \
    --no-install-recommends -qq

success "System packages installed."

# =============================================================================
#  STEP 3 — Python virtual environment
# =============================================================================
section "Step 3: Setting up Python virtual environment"

if [[ -d "$VENV_DIR" ]]; then
    warn "Virtual environment already exists at $VENV_DIR — skipping creation."
else
    info "Creating virtual environment…"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "Virtual environment created."
fi

info "Upgrading pip…"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip

info "Installing Python dependencies (this may take a few minutes on Pi)…"
"$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"
success "Python dependencies installed."

# =============================================================================
#  STEP 4 — Logs directory
# =============================================================================
section "Step 4: Creating logs directory"

mkdir -p "$LOG_DIR"
success "Logs directory: $LOG_DIR"

# =============================================================================
#  STEP 5 — SSH key generation
# =============================================================================
section "Step 5: SSH key for SFTP deployment"

KEY_PATH="$HOME/.ssh/id_ed25519_threatlandscape"

if [[ -f "$KEY_PATH" ]]; then
    warn "SSH key already exists at $KEY_PATH — skipping generation."
else
    info "Generating SSH key pair for deployment…"
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    ssh-keygen -t ed25519 -C "threatlandscape-deploy" -f "$KEY_PATH" -N ""
    success "SSH key generated: $KEY_PATH"
fi

echo ""
echo -e "${BOLD}Your SSH public key (add this to your web host's authorised_keys):${RESET}"
echo -e "${YELLOW}$(cat "${KEY_PATH}.pub")${RESET}"
echo ""

# =============================================================================
#  STEP 6 — .env credentials file
# =============================================================================
section "Step 6: Configuring credentials"

if [[ -f "$ENV_FILE" ]]; then
    warn ".env file already exists — skipping. Edit it manually if needed: $ENV_FILE"
else
    echo ""
    echo -e "${BOLD}Enter your SFTP credentials.${RESET}"
    echo "  Leave SFTP_PASSWORD blank if you are using SSH key authentication (recommended)."
    echo ""

    read -rp "  SFTP_HOST (e.g. barrycheevers.co.uk): " SFTP_HOST
    read -rp "  SFTP_USER (your SFTP username):        " SFTP_USER
    read -rp "  SFTP_PORT (default 22):                " SFTP_PORT_INPUT
    SFTP_PORT="${SFTP_PORT_INPUT:-22}"

    echo "  Authentication method:"
    echo "    1) SSH key  (recommended — key generated in step 5)"
    echo "    2) Password"
    read -rp "  Choice [1/2]: " AUTH_CHOICE

    cat > "$ENV_FILE" <<EOF
SFTP_HOST=${SFTP_HOST}
SFTP_USER=${SFTP_USER}
SFTP_PORT=${SFTP_PORT}
EOF

    if [[ "${AUTH_CHOICE}" == "2" ]]; then
        read -rsp "  SFTP_PASSWORD: " SFTP_PASSWORD
        echo ""
        echo "SFTP_PASSWORD=${SFTP_PASSWORD}" >> "$ENV_FILE"
        warn "Password stored in .env — ensure this file stays private."
    else
        echo "SFTP_KEY_PATH=${KEY_PATH}" >> "$ENV_FILE"
        success "SSH key path written to .env"
    fi

    chmod 600 "$ENV_FILE"
    success ".env created with permissions 600: $ENV_FILE"
fi

# =============================================================================
#  STEP 7 — Trust the SFTP server host key
# =============================================================================
section "Step 7: Trusting SFTP server host key"

# Read SFTP_HOST from .env (if set)
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source <(grep -E '^(SFTP_HOST|SFTP_PORT)=' "$ENV_FILE" | sed 's/^/export /')
fi

if [[ -z "${SFTP_HOST:-}" ]]; then
    warn "SFTP_HOST not set — skipping host key trust step. Run manually:"
    warn "  ssh-keyscan -p <PORT> <HOST> >> ~/.ssh/known_hosts"
else
    PORT="${SFTP_PORT:-22}"
    if ssh-keygen -F "${SFTP_HOST}" &>/dev/null; then
        success "Host key for ${SFTP_HOST} already in known_hosts."
    else
        info "Adding host key for ${SFTP_HOST}:${PORT} to known_hosts…"
        mkdir -p "$HOME/.ssh"
        chmod 700 "$HOME/.ssh"
        touch "$HOME/.ssh/known_hosts"
        chmod 600 "$HOME/.ssh/known_hosts"
        ssh-keyscan -p "${PORT}" "${SFTP_HOST}" >> "$HOME/.ssh/known_hosts" 2>/dev/null \
            && success "Host key added. Verify the fingerprint matches your host provider's documentation." \
            || warn "ssh-keyscan failed for ${SFTP_HOST}:${PORT}. Connect manually first: ssh ${SFTP_USER:-user}@${SFTP_HOST}"
    fi
fi

# =============================================================================
#  STEP 8 — Cron job
# =============================================================================
section "Step 8: Scheduling daily cron job"

CRON_CMD="cd ${PROJECT_DIR} && ${VENV_DIR}/bin/python -m src.main run-all >> ${LOG_DIR}/pipeline.log 2>&1"
CRON_LINE="CRON_TZ=Europe/London"$'\n'"0 7 * * * ${CRON_CMD}"

# Check if a cron entry for this project already exists
if crontab -l 2>/dev/null | grep -qF "$PROJECT_DIR"; then
    warn "A cron entry referencing $PROJECT_DIR already exists — skipping."
    info "Current crontab:"
    crontab -l 2>/dev/null | grep "$PROJECT_DIR" || true
else
    # Append to existing crontab (preserve any existing jobs)
    (crontab -l 2>/dev/null; echo ""; echo "# Threat Landscape Pipeline — daily run at 07:00 Europe/London"; echo "$CRON_LINE") | crontab -
    success "Cron job added: runs at 07:00 Europe/London every day."
    info "Full cron entry:"
    crontab -l | grep -A1 "Threat Landscape" || true
fi

# =============================================================================
#  STEP 9 — logrotate
# =============================================================================
section "Step 9: Setting up log rotation"

LOGROTATE_CONF="/etc/logrotate.d/threatlandscape"

if [[ -f "$LOGROTATE_CONF" ]]; then
    warn "Logrotate config already exists: $LOGROTATE_CONF — skipping."
else
    sudo tee "$LOGROTATE_CONF" > /dev/null <<EOF
${LOG_DIR}/pipeline.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 0640 $(whoami) $(whoami)
}
EOF
    success "Logrotate config written to $LOGROTATE_CONF"
fi

# =============================================================================
#  STEP 10 — Optional: run a test build
# =============================================================================
section "Step 10: Test build"

echo ""
read -rp "Run a test build now to verify everything works? [y/N]: " DO_BUILD

if [[ "${DO_BUILD,,}" == "y" ]]; then
    info "Running pipeline build (collecting from live sources — may take ~30 seconds)…"
    if "$VENV_DIR/bin/python" -m src.main build; then
        success "Build succeeded."
        echo ""
        echo "  Output files:"
        ls -lh "$PROJECT_DIR/output/" 2>/dev/null || true
    else
        error "Build failed. Check the output above for errors."
        echo "  You can re-run the build manually at any time:"
        echo "    source $VENV_DIR/bin/activate && python -m src.main build"
    fi
else
    info "Skipping test build. Run it manually when ready:"
    info "  source ${VENV_DIR}/bin/activate && python -m src.main build"
fi

# =============================================================================
#  Done
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${GREEN}  Setup complete!${RESET}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Add your SSH public key to your web host's authorised_keys:"
echo "       $(cat "${KEY_PATH}.pub" 2>/dev/null || echo "(see $KEY_PATH.pub)")"
echo ""
echo "  2. Verify the SFTP host key fingerprint matches your provider's docs."
echo ""
echo "  3. Test deployment:"
echo "       source ${VENV_DIR}/bin/activate && python -m src.main deploy"
echo ""
echo "  4. Install the WordPress plugin from:"
echo "       ${PROJECT_DIR}/wordpress_plugin/barry-threat-landscape/"
echo "     Then configure Settings > Threat Landscape in your WP admin."
echo ""
echo "  5. The pipeline will run automatically at 07:00 Europe/London every day."
echo "     Logs: ${LOG_DIR}/pipeline.log"
echo ""
