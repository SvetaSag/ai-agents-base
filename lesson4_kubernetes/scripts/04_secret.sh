#!/bin/bash
# Кладёт ключ OpenRouter из .env в Secret llm-secret (в git и в манифесты ключ не попадает).
set -e
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "❌ нет .env: cp .env.example .env и впишите OPENROUTER_API_KEY"; exit 1; }
set -a; . ./.env; set +a
[ -n "$OPENROUTER_API_KEY" ] || { echo "❌ в .env пустой OPENROUTER_API_KEY"; exit 1; }

# create … --dry-run | apply — создать, а если уже есть, обновить
kubectl create secret generic llm-secret --from-literal=OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
echo "✅ Secret llm-secret готов. Уже запущенные агенты увидят новый ключ только после перезапуска:"
echo "   kubectl rollout restart deploy/analyst deploy/risk-manager"
