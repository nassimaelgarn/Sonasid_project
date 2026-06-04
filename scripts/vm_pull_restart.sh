#!/usr/bin/env bash
# À exécuter SUR la VM (après git push depuis votre Mac).
# Met à jour le code + rbac/users versionnés, puis redémarre PM2.
set -euo pipefail

PROJECT_DIR="${SONASID_PROJECT_DIR:-/home/alexsys/sonasid/Sonasid_project}"
BRANCH="${SONASID_GIT_BRANCH:-main}"

cd "$PROJECT_DIR"
echo "==> git pull ($BRANCH) dans $PROJECT_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "==> redémarrage PM2"
pm2 restart my-backend my-frontend

echo "==> OK — déploiement terminé"
