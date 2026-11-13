#!/usr/bin/env bash
# One-time setup on a fresh Oracle Cloud Ubuntu server.
#   curl -fsSL https://raw.githubusercontent.com/varshith125/doculens1/main/deploy/oracle/setup.sh | bash -s -- yourname.duckdns.org
set -euo pipefail

DOMAIN="${1:?Usage: setup.sh yourname.duckdns.org}"
REPO="https://raw.githubusercontent.com/varshith125/doculens1/main/deploy/oracle"
APP_DIR="$HOME/doculens"

echo "==> Installing Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

echo "==> Opening ports 80 and 443 in the server firewall"
# Oracle's Ubuntu image rejects incoming traffic except SSH by default.
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 6 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
sudo apt-get install -y netfilter-persistent >/dev/null
sudo netfilter-persistent save

echo "==> Downloading DocuLens server files"
mkdir -p "$APP_DIR"
curl -fsSL "$REPO/docker-compose.yml" -o "$APP_DIR/docker-compose.yml"
curl -fsSL "$REPO/Caddyfile" -o "$APP_DIR/Caddyfile"
echo "DOMAIN=$DOMAIN" > "$APP_DIR/.env"

echo "==> Starting DocuLens (the first download is about 3 GB)"
cd "$APP_DIR"
sudo docker compose pull
sudo docker compose up -d

echo
echo "Done. In a minute or two, open https://$DOMAIN"
echo "Check status:  cd ~/doculens && sudo docker compose ps"
