# Intercloud Portal — Production Deployment (Ubuntu 24.04 LTS)

## One-command install

On a **fresh Ubuntu 24.04** server (as root or with `sudo`):

```bash
wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/install.sh
sudo bash install.sh
```

> Defaults baked in: `REPO_URL=https://github.com/PsychoX30/INTERCLOUD.git`,
> `PORTAL_DOMAIN=intercloud-digital.com`, `LETSENCRYPT_EMAIL=support@intercloud-digital.com`.
> Override any of them via env var if you're deploying from a fork, on a
> different domain, or with a different contact email:
>
> ```bash
> sudo REPO_URL="https://github.com/your-fork/INTERCLOUD.git" \
>      PORTAL_DOMAIN="portal.your-domain.com" \
>      LETSENCRYPT_EMAIL="ops@your-domain.com" \
>      bash install.sh
> ```

The installer runs end-to-end without prompts and configures:

1. **OS dependencies** — nginx, supervisor, python 3.12 + venv, node 20 +
   yarn, traceroute / dig / whois, mongodb-database-tools, fail2ban,
   certbot, jq.
2. **MongoDB 7.0** from the official APT repo, plus `security.authorization: enabled`
   with a per-install random-password user (`intercloud_app`, saved to
   `/etc/intercloud/mongo.env` mode 600). `bindIp` is pinned to `127.0.0.1`
   so Mongo is never exposed to the network.
3. **System user** `intercloud` and `git clone` of the repo into
   `/opt/intercloud-portal`.
4. **Python venv** + installs `backend/requirements.txt`.
5. **backend/.env** written with `MONGO_URL` that includes the freshly
   provisioned credentials, a random 48-byte `JWT_SECRET`, the
   `CORS_ORIGINS` whitelist (portal domain + www + localhost fallback),
   and the seed admin credentials. Existing `.env` files are preserved
   on re-run — safe to run the installer twice.
6. **frontend/.env** with `REACT_APP_BACKEND_URL` derived from
   `PORTAL_DOMAIN` (or the server's primary IP).
7. **Production build** — `yarn install --frozen-lockfile && yarn build`
   into `frontend/build/`, served by nginx.
8. **nginx reverse proxy** — `/api/` → `127.0.0.1:8001`, everything else
   → SPA build with `try_files … /index.html` fallback. Gzip on. Body
   size 100 MB (for backup restores). Read timeout 600s.
9. **supervisor** program `intercloud-backend` running
   `uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2`.
10. **UFW** firewall (22 / 80 / 443 allow, everything else deny).
11. **fail2ban** jails: SSH default + custom `nginx-portal-auth` that
    watches nginx access logs for repeated `401`/`429` responses on
    `/api/portal/auth/*` and bans offenders for 30 min after 20 hits in
    10 min.
12. **Daily backup cron** — `/etc/cron.d/intercloud-backup` runs
    `scripts/daily-backup.sh` at 03:15 UTC every day. Output:
    `/var/backups/intercloud/daily-YYYYMMDD.archive.gz` (gzipped BSON,
    atomic `.tmp`→final swap). Rolling **14-day retention**. Logs to
    `/var/log/intercloud-backup.log`.
13. **Let's Encrypt HTTPS via certbot** — if both `PORTAL_DOMAIN` and
    `LETSENCRYPT_EMAIL` are set and DNS points at the server, the script
    issues a cert non-interactively, rewrites the nginx config to
    redirect 80 → 443, and enables `certbot.timer` for auto-renewal.
    If DNS isn't ready or LETSENCRYPT_EMAIL is blank the install still
    completes on plain HTTP with a friendly warning.
13. **Admin seed verification** — polls the backend `/api/` health, then
    performs an actual login round-trip so the operator sees "Admin
    login OK" (or a clear warning) before the script exits.

Environment variables:

| var | default | notes |
| --- | --- | --- |
| `REPO_URL` | `https://github.com/PsychoX30/INTERCLOUD.git` | HTTPS git URL. Override for forks/mirrors. |
| `REPO_BRANCH` | `main` | Any branch/tag. |
| `APP_DIR` | `/opt/intercloud-portal` | Checkout location. |
| `PORTAL_DOMAIN` | `intercloud-digital.com` | FQDN → nginx server_name + CORS + certbot. |
| `LETSENCRYPT_EMAIL` | `support@intercloud-digital.com` | Certbot contact email; enables HTTPS. |
| `ENABLE_MONGO_AUTH` | `yes` | Set to `no` to skip auth (loopback only). |
| `MONGO_APP_USER` | `intercloud_app` | DB app user. |
| `MONGO_APP_PASSWORD` | *(random 32-byte)* | Auto-generated + saved. |
| `ADMIN_EMAIL` | `support@intercloud-digital.com` | Seed admin. Written to backend/.env; seeder resets the admin's password to this on first boot. |
| `ADMIN_PASSWORD` | `AdminIntercloud2026!` | Change after login. |
| `EMERGENT_LLM_KEY` | *(empty)* | Paste for AI features. |

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
