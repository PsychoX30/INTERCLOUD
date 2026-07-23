#!/usr/bin/env bash
#
# Intercloud Portal — one-command installer for Ubuntu 24.04 LTS.
#
# Usage (from a fresh Ubuntu 24.04 server, as root or sudo user):
#
#     wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/install.sh
#     sudo bash install.sh
#
# Options via environment variables (all optional):
#   REPO_URL     Git URL of the portal repo   (default: https://github.com/PsychoX30/INTERCLOUD.git)
#   REPO_BRANCH  Branch to check out          (default: main)
#   APP_DIR      Where to install             (default: /opt/intercloud-portal)
#   PORTAL_DOMAIN         Public FQDN         (default: intercloud-digital.com)
#   LETSENCRYPT_EMAIL     Email for certbot   (default: support@intercloud-digital.com)
#   ADMIN_EMAIL           Seed admin email    (default: support@intercloud-digital.com)
#   ADMIN_PASSWORD        Seed admin pw       (default: AdminIntercloud2026!)
#   EMERGENT_LLM_KEY      Optional: paste to enable AI features
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/PsychoX30/INTERCLOUD.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/intercloud-portal}"
PORTAL_DOMAIN="${PORTAL_DOMAIN:-intercloud-digital.com}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-support@intercloud-digital.com}"  # if set + PORTAL_DOMAIN, we run certbot
ENABLE_MONGO_AUTH="${ENABLE_MONGO_AUTH:-yes}"      # yes/no
MONGO_APP_USER="${MONGO_APP_USER:-intercloud_app}"
MONGO_APP_PASSWORD="${MONGO_APP_PASSWORD:-}"       # auto-generated if blank
ADMIN_EMAIL="${ADMIN_EMAIL:-support@intercloud-digital.com}"
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
  read -r -p "Git repository URL for the portal [https://github.com/PsychoX30/INTERCLOUD.git]: " REPO_URL
  REPO_URL="${REPO_URL:-https://github.com/PsychoX30/INTERCLOUD.git}"
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
  ufw fail2ban \
  certbot python3-certbot-nginx \
  jq

# ------------------------------------------------------------------
# 2. MongoDB (official APT repo). On Ubuntu 24.04 Noble we install
#    MongoDB 8.0 (first release with official Noble support). On older
#    Ubuntu we fall back to 7.0 from the jammy repo.
# ------------------------------------------------------------------
if ! command -v mongod >/dev/null 2>&1; then
  case "${VERSION_CODENAME:-}" in
    noble)  MONGO_SERIES="8.0"; MONGO_REPO_CODENAME="noble" ;;
    jammy)  MONGO_SERIES="7.0"; MONGO_REPO_CODENAME="jammy" ;;
    *)      MONGO_SERIES="7.0"; MONGO_REPO_CODENAME="jammy" ;;
  esac
  log "Installing MongoDB ${MONGO_SERIES} (repo codename: ${MONGO_REPO_CODENAME})"
  curl -fsSL "https://pgp.mongodb.com/server-${MONGO_SERIES}.asc" | \
    gpg -o "/usr/share/keyrings/mongodb-server-${MONGO_SERIES}.gpg" --dearmor --yes
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-${MONGO_SERIES}.gpg ] https://repo.mongodb.org/apt/ubuntu ${MONGO_REPO_CODENAME}/mongodb-org/${MONGO_SERIES} multiverse" \
    > "/etc/apt/sources.list.d/mongodb-org-${MONGO_SERIES}.list"
  apt-get update -y
  apt-get install -y mongodb-org mongodb-database-tools
  # Ensure the mongodb data dir has correct ownership before first start;
  # a leftover chown from a previous failed install is the #1 cause of
  # "mongod refuses to start" on fresh Ubuntu 24.04 hosts.
  install -d -o mongodb -g mongodb -m 0755 /var/lib/mongodb /var/log/mongodb
  systemctl daemon-reload
  systemctl enable --now mongod
else
  log "MongoDB already present — skipping install"
  systemctl start mongod || true
fi

# Wait for mongod to accept connections. If it never comes up we surface
# the systemd status + tail of the journal so the operator sees WHY it
# failed instead of the confusing downstream ECONNREFUSED.
log "Waiting for mongod to accept connections on 127.0.0.1:27017"
MONGO_UP=""
for i in {1..60}; do
  if mongosh --quiet --host 127.0.0.1 --port 27017 --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | grep -q 1; then
    MONGO_UP=1
    break
  fi
  # Every 10s, nudge systemd in case an earlier failed start left it down.
  if (( i % 10 == 0 )); then
    if ! systemctl is-active --quiet mongod; then
      warn "mongod not active after ${i}s — trying 'systemctl start mongod'"
      systemctl start mongod || true
    fi
  fi
  sleep 1
done
if [[ -z "$MONGO_UP" ]]; then
  echo
  warn "MongoDB did not come up within 60 seconds. Details:"
  systemctl status mongod --no-pager -l | sed -n '1,20p' || true
  echo "--- last 40 lines of journalctl -u mongod ---"
  journalctl -u mongod -n 40 --no-pager || true
  echo "--- /var/log/mongodb/mongod.log (last 40 lines) ---"
  tail -n 40 /var/log/mongodb/mongod.log 2>/dev/null || echo "(log file not created — mongod likely crashed before writing)"
  die "mongod is not running — cannot continue. Fix the errors above and re-run this installer."
fi

# ------------------------------------------------------------------
# 2b. MongoDB auth — create an app-scoped user and enable auth. Idempotent.
# ------------------------------------------------------------------
if [[ "$ENABLE_MONGO_AUTH" == "yes" ]]; then
  if [[ -z "$MONGO_APP_PASSWORD" ]]; then
    MONGO_APP_PASSWORD="$(openssl rand -base64 32 | tr -d '=+/')"
  fi

  # Detect whether auth is already configured. If /etc/mongod.conf has
  # `authorization: enabled` we're done setting up; just trust the existing
  # user record (we can't read the password anyway).
  if ! grep -qE '^\s*authorization:\s*enabled' /etc/mongod.conf; then
    log "Bootstrapping MongoDB user '${MONGO_APP_USER}' + enabling auth"
    # Create user while auth is still disabled so we don't need a bootstrap admin.
    mongosh --quiet <<MONGO
use admin
db.createUser({
  user: "${MONGO_APP_USER}",
  pwd:  "${MONGO_APP_PASSWORD}",
  roles: [
    { role: "readWrite", db: "intercloud_portal" },
    { role: "dbAdmin",   db: "intercloud_portal" },
    { role: "backup",    db: "admin" },
    { role: "restore",   db: "admin" }
  ]
})
MONGO
    # Flip auth on and restart. Keep bind to loopback only.
    sed -i 's/^\s*bindIp:.*/  bindIp: 127.0.0.1/' /etc/mongod.conf
    if grep -qE '^\s*#?\s*security:' /etc/mongod.conf; then
      sed -i 's/^\s*#\?\s*security:.*/security:\n  authorization: enabled/' /etc/mongod.conf
    else
      printf "\nsecurity:\n  authorization: enabled\n" >> /etc/mongod.conf
    fi
    systemctl restart mongod
    sleep 3
    # Save credentials for update.sh + future re-runs of this installer.
    install -o root -g root -m 600 /dev/stdin /etc/intercloud/mongo.env <<EOF
MONGO_APP_USER=${MONGO_APP_USER}
MONGO_APP_PASSWORD=${MONGO_APP_PASSWORD}
EOF
  else
    log "MongoDB auth already enabled — preserving existing credentials"
    # If we have the file from a previous run, load it so the .env below picks up matching credentials.
    if [[ -f /etc/intercloud/mongo.env ]]; then
      # shellcheck disable=SC1091
      . /etc/intercloud/mongo.env
    else
      warn "MongoDB auth is on but /etc/intercloud/mongo.env is missing — \
you'll need to set MONGO_URL manually in $APP_DIR/backend/.env"
    fi
  fi
  MONGO_URL_VALUE="mongodb://${MONGO_APP_USER}:${MONGO_APP_PASSWORD}@127.0.0.1:27017/intercloud_portal?authSource=admin"
else
  log "Skipping MongoDB auth setup (ENABLE_MONGO_AUTH=$ENABLE_MONGO_AUTH)"
  MONGO_URL_VALUE="mongodb://127.0.0.1:27017"
fi

mkdir -p /etc/intercloud

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
MONGO_URL="${MONGO_URL_VALUE}"
DB_NAME="intercloud_portal"
JWT_SECRET="$(openssl rand -base64 48 | tr -d '=+/' | head -c 48)"
CORS_ORIGINS="$CORS"
EMERGENT_LLM_KEY="${EMERGENT_LLM_KEY}"
ADMIN_EMAIL="${ADMIN_EMAIL}"
ADMIN_PASSWORD="${ADMIN_PASSWORD}"
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
# 8a. Daily backup cron — one archive per day, 14-day rolling window
# ------------------------------------------------------------------
log "Installing daily backup cron"
chmod +x "$APP_DIR/scripts/daily-backup.sh" 2>/dev/null || true
mkdir -p /var/backups/intercloud
chown -R intercloud:intercloud /var/backups/intercloud

# /etc/cron.d entry runs at 03:15 UTC (~10:15 WIB) daily, logs to syslog.
cat > /etc/cron.d/intercloud-backup <<CRON
# Managed by scripts/install.sh — regenerated on every install run.
# Daily gzipped BSON snapshot of the portal DB. Retention: 14 days.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
15 3 * * * root APP_DIR=$APP_DIR BACKUP_DIR=/var/backups/intercloud RETENTION_DAYS=14 bash $APP_DIR/scripts/daily-backup.sh >> /var/log/intercloud-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/intercloud-backup
touch /var/log/intercloud-backup.log
chown root:adm /var/log/intercloud-backup.log
chmod 640 /var/log/intercloud-backup.log

# ------------------------------------------------------------------
# 8b. fail2ban — protect SSH and nginx auth/login endpoints
# ------------------------------------------------------------------
if command -v fail2ban-server >/dev/null 2>&1; then
  log "Configuring fail2ban jails"
  cat > /etc/fail2ban/jail.d/intercloud.conf <<F2B
[sshd]
enabled  = true
maxretry = 5
bantime  = 1h

[nginx-portal-auth]
enabled  = true
filter   = nginx-portal-auth
logpath  = /var/log/nginx/access.log
maxretry = 20
findtime = 10m
bantime  = 30m
port     = http,https
F2B

  cat > /etc/fail2ban/filter.d/nginx-portal-auth.conf <<F2BFILTER
# Trip on repeated 401/429 responses to the auth endpoints
[Definition]
failregex = ^<HOST> - .* "POST /api/portal/auth/(login|register|forgot-password|reset-password)[^"]*" (401|429) .*$
ignoreregex =
F2BFILTER

  systemctl enable --now fail2ban
  systemctl restart fail2ban || true
fi

# ------------------------------------------------------------------
# 8c. Certbot — automatic HTTPS if PORTAL_DOMAIN + LETSENCRYPT_EMAIL set
# ------------------------------------------------------------------
if [[ -n "$PORTAL_DOMAIN" && -n "$LETSENCRYPT_EMAIL" ]]; then
  if certbot certificates 2>/dev/null | grep -q "Domains:.*\\b${PORTAL_DOMAIN}\\b"; then
    log "Let's Encrypt cert already exists for $PORTAL_DOMAIN — renewing"
    certbot renew --quiet --nginx || warn "certbot renew failed (non-fatal)"
  else
    log "Requesting Let's Encrypt cert for $PORTAL_DOMAIN"
    # Extra domain: www.$PORTAL_DOMAIN if reachable.
    EXTRA_D=""
    if getent hosts "www.$PORTAL_DOMAIN" >/dev/null 2>&1; then
      EXTRA_D="-d www.$PORTAL_DOMAIN"
    fi
    certbot --nginx --non-interactive --agree-tos \
      --email "$LETSENCRYPT_EMAIL" \
      --redirect \
      -d "$PORTAL_DOMAIN" $EXTRA_D \
      || warn "certbot failed — falling back to HTTP. Fix DNS + rerun:  sudo certbot --nginx -d $PORTAL_DOMAIN"
  fi
  systemctl enable --now certbot.timer 2>/dev/null || true
else
  warn "Skipping HTTPS — set PORTAL_DOMAIN and LETSENCRYPT_EMAIL to auto-issue a Let's Encrypt cert."
fi

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
# 10. Verify admin seed happened. The backend seeds an admin on first boot
# ----using INSTALL_ADMIN_EMAIL / INSTALL_ADMIN_PASSWORD. Poll the health
# ----endpoint until it's up, then try a login to confirm.
# ------------------------------------------------------------------
log "Waiting for backend to come online"
for i in {1..40}; do
  if curl -fsS "http://127.0.0.1:8001/api/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

log "Verifying admin login"
if LOGIN_HTTP=$(curl -sf -o /tmp/ic_login.json -w "%{http_code}" \
     -X POST "http://127.0.0.1:8001/api/portal/auth/login" \
     -H "Content-Type: application/json" \
     -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" 2>/dev/null); then
  if command -v jq >/dev/null 2>&1 && jq -e '.token' /tmp/ic_login.json >/dev/null 2>&1; then
    log "Admin login OK (HTTP $LOGIN_HTTP)"
  else
    warn "Login returned $LOGIN_HTTP but no token — seed may have failed. Check logs."
  fi
else
  warn "Admin login attempt failed. The admin seeder runs on the FIRST backend boot only;"
  warn "if this is a re-install with a pre-existing DB, use the password that was set originally."
fi
rm -f /tmp/ic_login.json

# ------------------------------------------------------------------
# 11. Done
# ------------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
PROTO="http"
if [[ -n "$PORTAL_DOMAIN" && -n "$LETSENCRYPT_EMAIL" ]] && \
   certbot certificates 2>/dev/null | grep -q "Domains:.*\\b${PORTAL_DOMAIN}\\b"; then
  PROTO="https"
fi
URL="${PROTO}://${PORTAL_DOMAIN:-$IP}"
cat <<DONE

$(tput setaf 2 2>/dev/null)============================================================
 Intercloud Portal installed successfully.
============================================================$(tput sgr0 2>/dev/null)

  App directory : $APP_DIR
  Portal URL    : $URL
  Backend       : 127.0.0.1:8001 (behind nginx /api)
  MongoDB       : 127.0.0.1:27017 ${ENABLE_MONGO_AUTH:+(auth enabled, user=${MONGO_APP_USER})}

  Admin login   : ${ADMIN_EMAIL}
  Admin passwd  : ${ADMIN_PASSWORD}

Automated in this run:
  ✓ OS dependencies + build tools
  ✓ MongoDB 7.0 ${ENABLE_MONGO_AUTH:++ auth}
  ✓ Node 20 + Yarn, Python 3.12 venv
  ✓ nginx reverse proxy (${PROTO})
  ✓ supervisor-managed uvicorn (2 workers)
  ✓ Daily backup cron (03:15 UTC, 14-day retention → /var/backups/intercloud)
  ✓ fail2ban jails (SSH + portal auth brute-force)
  ✓ UFW firewall (22 / 80 / 443)
$(if [[ "$PROTO" == "https" ]]; then echo "  ✓ Let's Encrypt HTTPS + auto-renewal via certbot.timer"; fi)

Next steps:
$(if [[ "$PROTO" != "https" && -n "$PORTAL_DOMAIN" ]]; then
   echo "  • For HTTPS: point $PORTAL_DOMAIN at $IP, then rerun with"
   echo "     LETSENCRYPT_EMAIL=you@example.com sudo bash install.sh"
fi)
  • Log in, then use $(tput bold 2>/dev/null)Admin ▸ Backup, Restore & Update$(tput sgr0 2>/dev/null) for future upgrades.
  • Store $(tput bold 2>/dev/null)/etc/intercloud/mongo.env$(tput sgr0 2>/dev/null) in your password manager.

Logs:
  Backend    :  tail -f /var/log/intercloud-backend.err.log
  nginx      :  tail -f /var/log/nginx/error.log
  MongoDB    :  journalctl -u mongod -f
  fail2ban   :  fail2ban-client status
DONE
