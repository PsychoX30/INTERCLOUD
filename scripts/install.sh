#!/usr/bin/env bash
#
# Intercloud Portal — one-command installer for Ubuntu 24.04 LTS.
#
# Usage (from a fresh Ubuntu 24.04 server, as root or sudo user):
#
#     wget -O install.sh https://raw.githubusercontent.com/<owner>/<repo>/main/scripts/install.sh
#     sudo bash install.sh
#
# Options via environment variables (all optional):
#   REPO_URL     Git URL of the portal repo   (default: env var, then prompt)
#   REPO_BRANCH  Branch to check out          (default: main)
#   APP_DIR      Where to install             (default: /opt/intercloud-portal)
#   PORTAL_DOMAIN         Public FQDN (e.g. portal.example.com); leave blank for IP-only
#   ADMIN_EMAIL           Seed admin email    (default: admin@intercloud-digital.com)
#   ADMIN_PASSWORD        Seed admin pw       (default: AdminIntercloud2026!)
#   EMERGENT_LLM_KEY      Optional: paste to enable AI features
#
set -euo pipefail

REPO_URL="${REPO_URL:-}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/intercloud-portal}"
PORTAL_DOMAIN="${PORTAL_DOMAIN:-}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@intercloud-digital.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-AdminIntercloud2026!}"
EMERGENT_LLM_KEY="${EMERGENT_LLM_KEY:-}"

BOLD=$(tput bold 2>/dev/null || echo "")
GREEN=$(tput setaf 2 2>/dev/null || echo "")
YELLOW=$(tput setaf 3 2>/dev/null || echo "")
RED=$(tput setaf 1 2>/dev/null || echo "")
RESET=$(tput sgr0 2>/dev/null || echo "")

log()  { echo -e "${BOLD}${GREEN}==>${RESET} $*"; }
warn() { echo -e "${BOLD}${YELLOW}!!${RESET} $*" >&2; }
die()  { echo -e "${BOLD}${RED}xx${RESET} $*" >&2; exit 1; }

# ------------------------------------------------------------------
# 0. Preflight
# ------------------------------------------------------------------
[[ $EUID -eq 0 ]] || die "Run as root or with sudo. Try: sudo bash install.sh"

. /etc/os-release || die "Cannot read /etc/os-release"
[[ "$VERSION_ID" == "24.04" ]] || warn "This script targets Ubuntu 24.04 LTS. You are on $PRETTY_NAME — continuing but expect issues."

if [[ -z "$REPO_URL" ]]; then
  read -r -p "Git repository URL for the portal (e.g. https://github.com/you/portal.git): " REPO_URL
fi
[[ -n "$REPO_URL" ]] || die "REPO_URL is required."

export DEBIAN_FRONTEND=noninteractive

# ------------------------------------------------------------------
# 1. OS packages
# ------------------------------------------------------------------
log "Updating apt index"
apt-get update -y

log "Installing OS dependencies"
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg lsb-release \
  git build-essential pkg-config \
  python3.12 python3.12-venv python3-pip \
  nginx supervisor \
  traceroute dnsutils whois iproute2 \
  ufw

# ------------------------------------------------------------------
# 2. MongoDB 7.0 (official APT repo, matches Ubuntu 24.04 support)
# ------------------------------------------------------------------
if ! command -v mongod >/dev/null 2>&1; then
  log "Installing MongoDB 7.0"
  curl -fsSL https://pgp.mongodb.com/server-7.0.asc | \
    gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor --yes
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list
  apt-get update -y
  apt-get install -y mongodb-org mongodb-database-tools
  systemctl enable --now mongod
else
  log "MongoDB already present — skipping install"
fi

# ------------------------------------------------------------------
# 3. Node.js 20 LTS + Yarn (classic)
# ------------------------------------------------------------------
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -c2-3)" -lt 20 ]]; then
  log "Installing Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
if ! command -v yarn >/dev/null 2>&1; then
  log "Installing Yarn"
  npm install -g yarn
fi

# ------------------------------------------------------------------
# 4. App user + clone
# ------------------------------------------------------------------
if ! id -u intercloud >/dev/null 2>&1; then
  log "Creating system user 'intercloud'"
  useradd --system --home "$APP_DIR" --shell /bin/bash --create-home intercloud
fi

if [[ -d "$APP_DIR/.git" ]]; then
  log "Existing repo at $APP_DIR — pulling latest"
  su - intercloud -c "cd '$APP_DIR' && git fetch --all && git checkout '$REPO_BRANCH' && git pull --ff-only"
else
  log "Cloning $REPO_URL → $APP_DIR"
  rm -rf "$APP_DIR"
  su - intercloud -c "git clone --branch '$REPO_BRANCH' '$REPO_URL' '$APP_DIR'"
fi

# ------------------------------------------------------------------
# 5. Backend — venv + deps + .env
# ------------------------------------------------------------------
log "Setting up Python venv + backend deps"
su - intercloud -c "
  cd '$APP_DIR/backend'
  python3.12 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip wheel
  pip install -r requirements.txt
"

BACKEND_ENV="$APP_DIR/backend/.env"
if [[ ! -f "$BACKEND_ENV" ]]; then
  log "Writing $BACKEND_ENV (defaults; edit any time)"
  # Origins: allow the portal domain + localhost variants + any raw IP
  if [[ -n "$PORTAL_DOMAIN" ]]; then
    CORS="https://$PORTAL_DOMAIN,https://www.$PORTAL_DOMAIN,http://$PORTAL_DOMAIN,http://localhost:3000"
  else
    CORS="*"
  fi
  install -o intercloud -g intercloud -m 640 /dev/stdin "$BACKEND_ENV" <<EOF
MONGO_URL="mongodb://127.0.0.1:27017"
DB_NAME="intercloud_portal"
JWT_SECRET="$(head -c 48 /dev/urandom | base64 | tr -d '=+/')"
CORS_ORIGINS="$CORS"
EMERGENT_LLM_KEY="${EMERGENT_LLM_KEY}"
INSTALL_ADMIN_EMAIL="${ADMIN_EMAIL}"
INSTALL_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
EOF
else
  log "Backend .env exists — preserving as-is"
fi

# ------------------------------------------------------------------
# 6. Frontend — deps + production build
# ------------------------------------------------------------------
log "Installing frontend deps and building production bundle"

FRONTEND_ENV="$APP_DIR/frontend/.env"
if [[ ! -f "$FRONTEND_ENV" ]]; then
  if [[ -n "$PORTAL_DOMAIN" ]]; then
    BACKEND_ORIGIN="https://$PORTAL_DOMAIN"
  else
    BACKEND_ORIGIN="http://$(hostname -I | awk '{print $1}')"
  fi
  install -o intercloud -g intercloud -m 640 /dev/stdin "$FRONTEND_ENV" <<EOF
REACT_APP_BACKEND_URL=$BACKEND_ORIGIN
EOF
else
  log "Frontend .env exists — preserving"
fi

su - intercloud -c "
  cd '$APP_DIR/frontend'
  yarn install --frozen-lockfile
  # Fall back to loose install if lockfile is stale — production must build.
  yarn build || (yarn install && yarn build)
"

# ------------------------------------------------------------------
# 7. nginx — reverse proxy / static + /api
# ------------------------------------------------------------------
log "Writing /etc/nginx/sites-available/intercloud"
cat > /etc/nginx/sites-available/intercloud <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${PORTAL_DOMAIN:-_};

    client_max_body_size 100M;   # backup restores upload archives here
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # SPA static bundle
    root $APP_DIR/frontend/build;
    index index.html;

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;   # backups + restores can take a while
    }

    # SPA fallback — every unmatched path serves the React app
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/intercloud /etc/nginx/sites-enabled/intercloud
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ------------------------------------------------------------------
# 8. supervisor — backend uvicorn only (frontend is static)
# ------------------------------------------------------------------
log "Writing /etc/supervisor/conf.d/intercloud-backend.conf"
cat > /etc/supervisor/conf.d/intercloud-backend.conf <<SUP
[program:intercloud-backend]
directory=$APP_DIR/backend
command=$APP_DIR/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2
autostart=true
autorestart=true
user=intercloud
environment=PATH="$APP_DIR/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
stdout_logfile=/var/log/intercloud-backend.out.log
stderr_logfile=/var/log/intercloud-backend.err.log
stopasgroup=true
killasgroup=true
SUP

supervisorctl reread
supervisorctl update
supervisorctl restart intercloud-backend || true

# ------------------------------------------------------------------
# 9. Firewall (optional but sensible)
# ------------------------------------------------------------------
log "Enabling ufw firewall (22 / 80 / 443)"
ufw --force disable >/dev/null || true
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable >/dev/null

# ------------------------------------------------------------------
# 10. Done
# ------------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
cat <<DONE

$(tput setaf 2 2>/dev/null)============================================================
 Intercloud Portal installed successfully.
============================================================$(tput sgr0 2>/dev/null)

  App directory : $APP_DIR
  Backend       : http://127.0.0.1:8001 (behind nginx /api)
  Frontend      : http://$IP/ (served by nginx from build/)
  MongoDB       : 127.0.0.1:27017 (local, no auth by default)

  Admin login   : ${ADMIN_EMAIL}
  Admin passwd  : ${ADMIN_PASSWORD}

Next steps:
  1. Point DNS 'A' record for $(tput bold 2>/dev/null)${PORTAL_DOMAIN:-your domain}$(tput sgr0 2>/dev/null) at $IP.
  2. For HTTPS, run:  sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d ${PORTAL_DOMAIN:-YOUR_DOMAIN}
  3. Test the update endpoint from Admin ▸ Backup & Restore ▸ "Update system".
  4. Optional: MongoDB auth — see docs/production.md.

Logs:
  Backend  :  tail -f /var/log/intercloud-backend.err.log
  nginx    :  tail -f /var/log/nginx/error.log
  Mongo    :  journalctl -u mongod -f
DONE
