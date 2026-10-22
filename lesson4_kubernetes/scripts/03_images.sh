#!/bin/bash
# Собирает образы агентов прямо в кластере, сразу на всех нодах (Docker на Mac не нужен).
set -e
cd "$(dirname "$0")/.."

echo "🔨 hello-agent:1 и hello-agent:2 (части 1–4)"
minikube image build --all -t hello-agent:1 --build-opt=build-arg=VERSION=1 images/hello-agent
minikube image build --all -t hello-agent:2 --build-opt=build-arg=VERSION=2 images/hello-agent

echo "🔨 bank-agents:1 — MCP-сервер, аналитик, риск-менеджер, загрузчик данных (части 5–8)"
minikube image build --all -t bank-agents:1 images/agents

echo "✅ Образы на нодах:"
minikube image ls | grep -E "hello-agent|bank-agents"
