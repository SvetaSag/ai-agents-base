#!/bin/bash

set -e

# Остановка существующего кластера (если есть)
minikube stop || true
minikube delete || true

# Запуск Minikube с 3 нодами
echo "Starting Minikube cluster with 3 nodes..."

# Для macos я использую qemu, так как docker не работает на моем MacBook
minikube start --driver qemu --nodes 3 --cpus 3 --memory 8G --disk-size 80G

# Включение аддонов
echo "Enabling addons..."
minikube addons enable ingress
minikube addons enable metrics-server
minikube addons enable dashboard

# Настройка Ingress
# echo "Setting up Ingress..."
# ./scripts/setup-ingress.sh || echo "Ingress setup will be done separately"

# Установка Helm (если не установлен)
if ! command -v helm &> /dev/null; then
    echo "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Добавление Helm репозиториев
echo "Adding Helm repositories..."
helm repo add elastic https://helm.elastic.co
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update