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
CORS_VAL="https://sonasid-alexsys.westeurope.cloudapp.azure.com,http://sonasid-alexsys.westeurope.cloudapp.azure.com,http://sonasid-alexsys.westeurope.cloudapp.azure.com:5175,http://135.236.108.108,http://135.236.108.108:5175"
grep -q '^CORS_ORIGINS=' "$ENV_FILE" && sed -i.bak \
  "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$CORS_VAL|" \
  "$ENV_FILE" || echo "CORS_ORIGINS=$CORS_VAL" >> "$ENV_FILE"

echo "==> Dépendances Python (python-multipart pour /chat/stt)"
if [[ -f "$PROJECT_DIR/.venv/bin/pip" ]]; then
  "$PROJECT_DIR/.venv/bin/pip" install -q python-multipart || true
elif [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
  pip install -q -r "$PROJECT_DIR/requirements.txt" || true
fi

echo "==> PM2 restart (backend d'abord)"
pm2 restart my-backend --update-env || pm2 start my-backend --update-env || true
sleep 2
pm2 restart my-frontend --update-env || pm2 start my-frontend --update-env || true
sleep 2
pm2 status || true

echo "==> Test healthz (localhost:8001)"
if curl -sf http://127.0.0.1:8001/healthz | head -c 120; then
  echo ""
  echo "backend OK"
else
  echo ""
  echo "WARN: backend KO sur :8001 — voir: pm2 logs my-backend --lines 40"
fi

echo "==> Test login local"
curl -sf -X POST http://127.0.0.1:8001/auth/local/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"abdelkaioume.ammour","password":"Am1122"}' | head -c 120 \
  || echo "(login local KO)"
echo ""

echo "==> Test via nginx HTTPS"
curl -sfk https://sonasid-alexsys.westeurope.cloudapp.azure.com/healthz | head -c 120 \
  || echo "(healthz HTTPS KO — vérifier nginx + backend)"
echo ""

echo ""
echo "URLs :"
echo "  https://sonasid-alexsys.westeurope.cloudapp.azure.com  (recommandé — micro OK)"
echo "  http://135.236.108.108:5175  (secours direct Vite)"
