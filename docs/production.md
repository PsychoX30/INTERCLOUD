# Intercloud Portal — Production Deployment (Ubuntu 24.04 LTS)

## One-command install

On a **fresh Ubuntu 24.04** server (as root or with `sudo`):

```bash
wget -O install.sh https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install.sh
sudo REPO_URL="https://github.com/<OWNER>/<REPO>.git" \
     PORTAL_DOMAIN="portal.your-domain.com" \
     bash install.sh
```

The installer:

1. Installs OS packages (nginx, supervisor, python 3.12, node 20, yarn,
   traceroute/dig/whois, mongodb-database-tools).
2. Installs **MongoDB 7.0** from the official APT repo and enables it.
3. Creates a system user `intercloud` and clones the repo into
   `/opt/intercloud-portal`.
4. Sets up a Python venv + installs `backend/requirements.txt`.
5. Writes `backend/.env` (with a random 48-byte JWT secret) and
   `frontend/.env` — **existing .env files are preserved on re-run**.
6. Runs `yarn install && yarn build` — nginx serves the SPA out of
   `frontend/build/`.
7. Configures `nginx` as a reverse proxy: `/api` → `127.0.0.1:8001`,
   everything else → the SPA build with a `try_files` fallback.
8. Registers a supervisor program `intercloud-backend` that runs
   `uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2`.
9. Enables `ufw` and opens 22 / 80 / 443.

Environment variables consumed:

| var | default | notes |
| --- | --- | --- |
| `REPO_URL` | *(prompts)* | Required. HTTPS git URL. |
| `REPO_BRANCH` | `main` | Any branch/tag. |
| `APP_DIR` | `/opt/intercloud-portal` | Where the repo lives. |
| `PORTAL_DOMAIN` | *(empty)* | If set, becomes the nginx `server_name` and the CORS whitelist. |
| `ADMIN_EMAIL` | `admin@intercloud-digital.com` | Seeded on first backend boot. |
| `ADMIN_PASSWORD` | `AdminIntercloud2026!` | Change after login. |
| `EMERGENT_LLM_KEY` | *(empty)* | Paste to enable AI features. |

## HTTPS (recommended)

After DNS points at the server:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d portal.your-domain.com
```

Certbot rewrites the nginx config to redirect 80 → 443 automatically.

## Updates — two options

### From the Admin UI

Log in → **Admin ▸ Backup, Restore & Update** → click **Update to latest release**.

The button hits `POST /api/portal/admin/system/update?confirm=UPDATE`, which
runs `scripts/update.sh` server-side. The script:

- Dumps the DB to `/var/backups/intercloud/pre-update-<UTC>.archive.gz`
  (30-day rolling retention).
- `git pull --ff-only` on the current branch.
- Reinstalls Python + Node deps.
- Rebuilds the frontend production bundle.
- Restarts the backend via supervisor (nginx keeps serving the old bundle
  during the ~30 s build, so downtime is measured in seconds).

Response includes the log tail plus the STATUS line:

```
STATUS=ok OLD=<sha-before> NEW=<sha-after> BACKUP=/var/backups/intercloud/pre-update-*.archive.gz
```

### From the shell

```bash
sudo -u intercloud bash /opt/intercloud-portal/scripts/update.sh
```

Same behaviour, useful for scripted deploys or when the API is
temporarily unreachable.

## Backup / Restore

- Manual snapshot: **Admin ▸ Backup, Restore & Update ▸ Download backup**.
- Manual restore: same page, drop the archive, type `REPLACE`, click.
- Automated (every update): kept under `/var/backups/intercloud`.
- Recommend: rsync `/var/backups/intercloud` to off-site storage nightly.

## Files touched by the installer

| Path | Purpose |
| --- | --- |
| `/opt/intercloud-portal` | The app checkout |
| `/opt/intercloud-portal/backend/.env` | Backend secrets (preserved on update) |
| `/opt/intercloud-portal/frontend/.env` | `REACT_APP_BACKEND_URL` (preserved) |
| `/opt/intercloud-portal/frontend/build/` | Nginx doc-root |
| `/etc/nginx/sites-available/intercloud` | Reverse proxy config |
| `/etc/supervisor/conf.d/intercloud-backend.conf` | uvicorn process |
| `/var/log/intercloud-backend.*.log` | Backend logs |
| `/var/backups/intercloud/` | Pre-update DB snapshots |

## Troubleshooting

- **`502 Bad Gateway` from nginx** — backend isn't running.
  `sudo supervisorctl status intercloud-backend`
  `tail -f /var/log/intercloud-backend.err.log`

- **Update button spins forever** — the script may be rebuilding the frontend;
  first-time builds take 60-90 s on modest hardware. The endpoint times out
  at 10 minutes.

- **`git pull` fails with local changes** — the update script auto-stashes
  under `update.sh @ <timestamp>`. Recover with `git stash list && git stash pop`.
