# How To Install on Ubuntu 24.04 LTS
wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/install.sh
sudo bash install.sh 2>&1 | tee -a /tmp/install.log

# How To Reinstall
Create purge.sh

#!/bin/bash
set -e

echo "==> Stopping services"
sudo systemctl stop supervisor nginx mongod 2>/dev/null || true
sudo supervisorctl stop all 2>/dev/null || true

echo "==> Purging MongoDB (packages, data, logs, config, apt source)"
sudo apt-get purge -y 'mongodb-org*' 'mongodb-database-tools' 'mongodb-mongosh' 2>/dev/null || true
sudo rm -rf /var/lib/mongodb /var/log/mongodb /etc/mongod.conf* \
            /etc/apt/sources.list.d/mongodb-org-*.list \
            /usr/share/keyrings/mongodb-server-*.gpg

echo "==> Purging Node.js apt source (keep node binary; installer detects & skips)"
sudo rm -f /etc/apt/sources.list.d/nodesource.list /usr/share/keyrings/nodesource.gpg
sudo apt-get purge -y nodejs && sudo rm -rf /usr/lib/node_modules

echo "==> Removing portal install + user + credentials"
sudo rm -rf /opt/intercloud-portal /etc/intercloud
sudo userdel -r intercloud 2>/dev/null || true

echo "==> Removing nginx site + certbot cert for portal domain"
sudo rm -f /etc/nginx/sites-enabled/intercloud-portal /etc/nginx/sites-available/intercloud-portal
sudo certbot delete --cert-name intercloud-digital.com --non-interactive 2>/dev/null || true
sudo rm -rf /etc/letsencrypt/live/intercloud-digital.com* \
            /etc/letsencrypt/renewal/intercloud-digital.com.conf \
            /etc/letsencrypt/archive/intercloud-digital.com*

echo "==> Removing supervisor programs for portal"
sudo rm -f /etc/supervisor/conf.d/intercloud-*.conf
sudo supervisorctl reread 2>/dev/null || true
sudo supervisorctl update 2>/dev/null || true

echo "==> Removing fail2ban jail + backup cron + log files"
sudo rm -f /etc/fail2ban/jail.d/intercloud-portal.conf \
           /etc/cron.d/intercloud-daily-backup \
           /var/log/intercloud-backup.log
sudo systemctl restart fail2ban 2>/dev/null || true

echo "==> Cleaning previous install artifacts + apt cache"
sudo rm -f /tmp/install.log ~/install.sh
sudo apt-get autoremove -y
sudo apt-get autoclean

echo "==> Restarting core services"
sudo systemctl start nginx supervisor 2>/dev/null || true
echo ""
echo "✅ Purge complete. Sanity check:"
which mongod || echo "  mongod: gone"
id intercloud 2>/dev/null || echo "  user 'intercloud': gone"
ls /opt/intercloud-portal 2>/dev/null || echo "  /opt/intercloud-portal: gone"
ls /etc/intercloud 2>/dev/null || echo "  /etc/intercloud: gone"
sudo rm -rf install.sh
echo ""
echo "==> Ready for fresh install:"
echo "   wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/ins>
echo "   sudo bash install.sh 2>&1 | tee /tmp/install.log"

sudo wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/install.sh
sudo bash install.sh 2>&1 | tee -a /tmp/install.log
