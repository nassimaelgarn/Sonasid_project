#!/usr/bin/env bash
# Configure les 3 modèles Azure (Grok, Kimi, DeepSeek) dans .env sur la VM.
#
# Usage (sur la VM) :
#   AZURE_OPENAI_API_KEY='votre_cle' bash scripts/vm_setup_azure_models.sh
#
# La clé n'est jamais commitée — passez-la en variable d'environnement ou éditez .env après.
set -euo pipefail

PROJECT_DIR="${SONASID_PROJECT_DIR:-/home/alexsys/sonasid/Sonasid_project}"
ENV_FILE="$PROJECT_DIR/.env"
cd "$PROJECT_DIR"

touch "$ENV_FILE"

set_or_append() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

KEY="${AZURE_OPENAI_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  KEY="$(grep -E '^AZURE_OPENAI_API_KEY=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'" || true)"
fi
if [[ -z "$KEY" ]]; then
  echo "ERREUR: AZURE_OPENAI_API_KEY manquante."
  echo "  AZURE_OPENAI_API_KEY='...' bash scripts/vm_setup_azure_models.sh"
  exit 1
fi

echo "==> Variables Azure dans $ENV_FILE"
set_or_append "AZURE_OPENAI_API_KEY" "$KEY"
set_or_append "AZURE_OPENAI_ENDPOINT" "https://ymaftouh-9045-resource.services.ai.azure.com/openai/v1"
set_or_append "AZURE_OPENAI_DEPLOYMENT_1" "Kimi-K2.6"
set_or_append "AZURE_OPENAI_LABEL_1" "Kimi K2.6"
set_or_append "AZURE_OPENAI_DEPLOYMENT_2" "DeepSeek-V4-Pro"
set_or_append "AZURE_OPENAI_LABEL_2" "DeepSeek V4 Pro"
set_or_append "AZURE_INFERENCE_ENDPOINT" "https://ymaftouh-9045-resource.services.ai.azure.com/models"
set_or_append "AZURE_INFERENCE_DEPLOYMENT" "grok-4.3"
set_or_append "AZURE_INFERENCE_LABEL" "Grok 4.3"
set_or_append "SONASID_DEFAULT_CHAT_MODEL" "kimi"
set_or_append "SONASID_NARRATE_MODEL" "kimi"
set_or_append "SONASID_CHAT_TEMPERATURE" "0.35"
set_or_append "SONASID_NARRATE_TEMPERATURE" "0.4"
set_or_append "USE_LLM" "true"

echo "==> PM2 restart backend (--update-env)"
pm2 restart my-backend --update-env || true
sleep 3

echo "==> Test GET /chat/models"
if curl -sf http://127.0.0.1:8001/chat/models | python3 -m json.tool 2>/dev/null | head -40; then
  echo ""
else
  curl -sf http://127.0.0.1:8001/chat/models | head -c 400 || echo "(endpoint KO)"
  echo ""
fi

echo ""
echo "Attendu : grok, kimi, deepseek, trinity, flash, ollama"
echo "Puis rafraîchir https://sonasid-alexsys.westeurope.cloudapp.azure.com"
