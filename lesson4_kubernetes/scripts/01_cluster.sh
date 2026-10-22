#!/bin/bash
# Учебный кластер: 3 ноды minikube на QEMU (macOS) + аддоны.
# Нужен сетевой демон socket_vmnet (один раз): sudo brew services start socket_vmnet
set -e

if [ ! -S /opt/homebrew/var/run/socket_vmnet ]; then
    echo "❌ socket_vmnet не запущен. Запустите: sudo brew services start socket_vmnet"
    exit 1
fi

minikube delete >/dev/null 2>&1 || true

echo "🚀 Запускаем minikube: 3 ноды на QEMU…"
# Ресурсы умеренные: 3 × (2 CPU, 4 ГБ RAM, 20 ГБ диска) — агентам хватает
minikube start --driver qemu --network socket_vmnet --nodes 3 --cpus 2 --memory 4g --disk-size 20g

echo "📦 Заранее качаем образы ingress на все ноды"
# kubelet бросает скачивание, если оно минуту не продвигается; при медленном registry.k8s.io
# ingress-контроллер тогда висит в ImagePullBackOff. docker pull на ноде такого лимита не имеет.
for image in $(minikube addons images ingress 2>/dev/null | awk -F'|' 'NF > 3 && $3 ~ /@sha256/ {gsub(/ /, ""); print $4 "/" $3}' | sort -u); do
    for node in $(kubectl get nodes -o name | cut -d/ -f2); do
        echo "   $node ← $image"
        minikube ssh -n "$node" -- docker pull -q "$image" >/dev/null
    done
done

echo "🧩 Аддоны: ingress (вход по домену) и metrics-server (kubectl top, автоскейлинг)"
minikube addons enable ingress || { echo "⚠️  ingress не успел подняться, пробуем ещё раз…"; minikube addons enable ingress; }
minikube addons enable metrics-server

kubectl get nodes -o wide
echo "✅ Кластер готов. IP: $(minikube ip)"
