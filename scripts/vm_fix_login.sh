#!/usr/bin/env bash
# Corrige login + domaine Azure sur la VM.
# Usage (sur la VM) : bash scripts/vm_fix_login.sh
set -euo pipefail

PROJECT_DIR="${SONASID_PROJECT_DIR:-/home/alexsys/sonasid/Sonasid_project}"
cd "$PROJECT_DIR"

echo "==> git pull"
git pull origin main || true

echo "==> CORS backend"
ENV_FILE="$PROJECT_DIR/.env"
touch "$ENV_FILE"
grep -q '^CORS_ORIGINS=' "$ENV_FILE" && sed -i.bak \
  's|^CORS_ORIGINS=.*|CORS_ORIGINS=http://135.236.108.108,http://135.236.108.108:5175,http://sonasid-alexsys.westeurope.cloudapp.azure.com,http://sonasid-alexsys.westeurope.cloudapp.azure.com:5175|' \
  "$ENV_FILE" || echo 'CORS_ORIGINS=http://135.236.108.108,http://135.236.108.108:5175,http://sonasid-alexsys.westeurope.cloudapp.azure.com,http://sonasid-alexsys.westeurope.cloudapp.azure.com:5175' >> "$ENV_FILE"

echo "==> Test API login"
curl -sf -X POST http://127.0.0.1:8001/auth/local/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"abdelkaioume.ammour","password":"Am1122"}' | head -c 100
echo ""

echo "==> PM2 restart (vite proxy + allowedHosts dans vite.config.js)"
pm2 restart my-backend my-frontend --update-env

echo ""
echo "URLs :"
echo "  http://135.236.108.108:5175"
echo "  http://sonasid-alexsys.westeurope.cloudapp.azure.com:5175"
echo "Login : abdelkaioume.ammour / Am1122"
