#!/usr/bin/env bash
# Depuis votre Mac : commit/push GitHub puis mise à jour automatique sur la VM (SSH).
# Usage: ./scripts/deploy_from_mac.sh "message de commit"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MSG="${1:-deploy: mise à jour Sonasid}"
VM_HOST="${SONASID_VM_HOST:-alexsys@135.236.108.108}"
VM_PROJECT="${SONASID_VM_PROJECT:-/home/alexsys/sonasid/Sonasid_project}"
BRANCH="${SONASID_GIT_BRANCH:-main}"

echo "==> git commit + push"
git add -A
if git diff --cached --quiet; then
  echo "Rien à committer."
else
  git commit -m "$MSG"
fi
git push origin "$BRANCH"

echo "==> git pull + pm2 restart sur la VM ($VM_HOST)"
ssh "$VM_HOST" "SONASID_PROJECT_DIR=$VM_PROJECT SONASID_GIT_BRANCH=$BRANCH bash -s" < "$ROOT/scripts/vm_pull_restart.sh"

echo "==> Déploiement terminé"
