#!/bin/bash

# Получаем IP minikube
MINIKUBE_IP=$(minikube ip 2>/dev/null)

# Проверяем, запущен ли minikube
if [ -z "$MINIKUBE_IP" ]; then
    echo "❌ Minikube не запущен. Запустите: minikube start"
    exit 1
fi

echo "🎯 IP Minikube: $MINIKUBE_IP"

# Временный файл
TEMP_HOSTS=$(mktemp)

# Обрабатываем /etc/hosts
while IFS= read -r line; do
    # Удаляем старые записи
    if [[ $line != *"hse-ai.ru"* && $line != *"kubernetes.docker.internal"* ]]; then
        echo "$line" >> "$TEMP_HOSTS"
    fi
done < /etc/hosts

# Добавляем kubernetes.docker.internal если его нет
if ! grep -q "kubernetes.docker.internal" "$TEMP_HOSTS"; then
    echo "127.0.0.1      kubernetes.docker.internal" >> "$TEMP_HOSTS"
fi

# Добавляем обновлённые записи hse-ai.ru
echo "$MINIKUBE_IP  hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  api.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  backend.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  mlflow.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  prometheus.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  grafana.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  kibana.hse-ai.ru" >> "$TEMP_HOSTS"
echo "$MINIKUBE_IP  argocd.hse-ai.ru" >> "$TEMP_HOSTS"

# Копируем обратно в /etc/hosts
sudo cp "$TEMP_HOSTS" /etc/hosts
sudo chmod 644 /etc/hosts

# Очистка
rm "$TEMP_HOSTS"

echo "✅ /etc/hosts обновлён с IP: $MINIKUBE_IP"
echo "📋 Проверка:"
grep "hse-ai.ru\|kubernetes.docker.internal" /etc/hosts