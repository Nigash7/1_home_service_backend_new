#!/usr/bin/env bash
#
# First-time setup for a fresh Ubuntu 24.04 EC2 box in ap-south-1 (Mumbai).
# Run once, as a user with sudo:
#
#   sudo bash deploy/setup_server.sh
#
# It does NOT create the .env, request the TLS certificate, or start the app --
# those need values only you have. deploy/README.md picks up where this stops.

set -euo pipefail

APP_DIR=/srv/homeservice
REPO=https://github.com/tribixsmedia-collab/1_home_service_backend_new.git
BRANCH=main

if [ "$EUID" -ne 0 ]; then
    echo "Run this with sudo." >&2
    exit 1
fi

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    postgresql-client \
    nginx git curl \
    certbot python3-certbot-nginx \
    unattended-upgrades

echo "==> Enabling automatic security updates"
# The box will be running unattended for months. Security patches should not
# wait for someone to remember.
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Fetching the code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH" --quiet
else
    mkdir -p "$APP_DIR"
    git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

echo "==> Building the virtualenv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> Creating the media and secrets directories"
# media/ holds vendor ID documents, which are the one thing on this box that
# exists nowhere else. See the backup section of deploy/README.md.
mkdir -p "$APP_DIR/media" "$APP_DIR/secrets"
chmod 750 "$APP_DIR/secrets"

echo "==> Setting ownership"
chown -R www-data:www-data "$APP_DIR"
chmod +x "$APP_DIR/deploy/deploy.sh"

echo "==> Installing the systemd units"
cp "$APP_DIR/deploy/gunicorn.socket"  /etc/systemd/system/homeservice.socket
cp "$APP_DIR/deploy/gunicorn.service" /etc/systemd/system/homeservice.service
systemctl daemon-reload
systemctl enable homeservice.socket

echo "==> Letting the deploy script restart the app without a password"
cat > /etc/sudoers.d/homeservice <<'SUDOERS'
www-data ALL=(root) NOPASSWD: /usr/bin/systemctl restart homeservice
SUDOERS
chmod 440 /etc/sudoers.d/homeservice

echo "==> Installing the nginx site"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/homeservice
ln -sf /etc/nginx/sites-available/homeservice /etc/nginx/sites-enabled/homeservice
rm -f /etc/nginx/sites-enabled/default

cat <<'NEXT'

==> Base system ready.

Still to do by hand, because each needs a value only you have:

  1. Put the real domain into /etc/nginx/sites-available/homeservice
     (replace api.example.com), then: sudo nginx -t && sudo systemctl reload nginx

  2. Create /srv/homeservice/.env from deploy/env.production.example
     sudo -u www-data nano /srv/homeservice/.env
     sudo chmod 600 /srv/homeservice/.env

  3. Get the HTTPS certificate:
     sudo certbot --nginx -d api.yourdomain.com

  4. Set up the database and start the app -- deploy/README.md, step 6 onward.

NEXT
