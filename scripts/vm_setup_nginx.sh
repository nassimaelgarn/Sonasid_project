#!/usr/bin/env bash
# Installe le reverse proxy nginx Sonasid (remplace la page "Welcome to nginx").
# Usage (sur la VM) : bash scripts/vm_setup_nginx.sh
set -euo pipefail

PROJECT_DIR="${SONASID_PROJECT_DIR:-/home/alexsys/sonasid/Sonasid_project}"
DOMAIN="${SONASID_DOMAIN:-sonasid-alexsys.westeurope.cloudapp.azure.com}"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

cd "$PROJECT_DIR"

echo "==> git pull"
git pull origin main || true

if ! sudo test -f "$CERT_DIR/fullchain.pem"; then
  echo "Certificat SSL absent ($CERT_DIR)."
  echo "Lance d'abord : sudo certbot --nginx -d $DOMAIN"
  exit 1
fi

echo "==> nginx site Sonasid"
sudo cp "$PROJECT_DIR/scripts/nginx-sonasid.conf" /etc/nginx/sites-available/sonasid
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/sonasid /etc/nginx/sites-enabled/sonasid

echo "==> nginx test + reload"
sudo nginx -t
sudo systemctl reload nginx

echo "==> CORS + PM2"
bash "$PROJECT_DIR/scripts/vm_fix_login.sh"

echo ""
echo "OK — URLs :"
echo "  https://$DOMAIN"
echo "  http://135.236.108.108  (sans SSL, micro indisponible)"
echo "  http://135.236.108.108:5175  (direct Vite, secours)"
