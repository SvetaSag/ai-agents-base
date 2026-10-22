## Выполняем сборку образа и пуш его в репозиторий
---
```bash
docker build --tag=aesedeu/nginx-hse-ai:1.0 --file=Dockerfile .
docker push aesedeu/nginx-hse-ai:1.0
# или
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t aesedeu/nginx-hse-ai:1.0 \
  -f Dockerfile \
  --push \
  .



# для локального запуска можно выполнить
docker run --rm -p 80:80 aesedeu/nginx-hse-ai:1.0
```


## Запускаем k8s
```bash
make setup
make update_hosts
```


## Part 1. Создание pod'ов
---
```bash
cd part_1
minikube image load ubuntu:24.04
minikube image ls
kubectl apply -f ubuntu_pod.yaml

kubectl apply -f pod_1.yaml
kubectl apply -f pod_2.yaml
```
Проходим в pod с ubuntu и видим что можем вызывать другие pod в сети и вызывать их по ip через curl. Создаем service:
```bash
kubectl apply -f service.yaml
```
Из pod с ubuntu вызываем через curl service. Теперь поднимаем ingress:
```bash
kubectl apply -f ingress.yaml
minikube tunnel
```
В `/etc/hosts` уже должен быть маппинг на IP minikube.

Видим что можем теперь по адресу в браузере переходить и видеть сайт.

Создаем replicaset:
```bash
kubectl apply -f replicaset.yaml
```
- Нам поможет RS, поднимаем его и видим что у нас 4 пода (2 из POD и 2 из RS)
- На фронте прилетают разные веб-страницы
- Удаляем под и видим что он автоматически возвращается
- Можно поменять количество подов в манифесте `replicaset`


## Part 2. Deployment + service
---
Удаляем все что было выше.

Теперь применяем деплоймент.
```bash
cd part_2
# обновляем ingress
kubectl apply -f ingress.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```
- Смотрим ревизию деплоймента `kubectl rollout history deployment/hse-deployment`
- Меняем образ контейнера, видим постепенно обновление контейнеров
- Пробуем выполнить откат (при это файл деплоймента не будет изменен) `kubectl rollout undo deployment hse-deployment`

Есть такое понятие как лейблы нод.
```bash
kubectl get nodes --show-labels

# Дадим лейбл ноде
kubectl label nodes minikube-m02 load=high

# Дописываем в деплоймент nodeSelector и выполняем апдейт
kubectl apply -f deployment.yaml
# Видим что поды все уехали на ноду. соответствующую селектору
```


## Part 3. Configmap + Secrets
```bash
# Останавливаем replicaset
kubectl delete -f replicaset.yaml

# Создаем CM и приписываем его в деплоймент (`/etc/config`)
kubectl apply -f configmap.yaml

# Создаем секреты
kubectl apply -f secrets.yaml

# Для конвертации из base64
echo -n 'admin' | base64     # → YWRtaW4=
echo -n 'secret' | base64    # → c2VjcmV0

# Применяем деплоймент
kubectl apply -f deployment.yaml

# Заходим в ubuntu pod
curl -s <SERVICE_IP> | grep Pod:
# Видим что имена подов разные, то есть запросы раскидываются корректно

# Secrets: проваливаемся в поднятые поды и видим что там также есть созданные нами переменные окружения
# ConfigMap: в подах по пути /etc/config будет созданный конфиг
```


## Part 4. Monitoring
```bash
cd part_4_monitoring

kubectl apply -f ingress-grafana.yaml
kubectl apply -f ingress-prometheus.yaml

kubectl create namespace monitoring
kubectl apply -f grafana-dashboard-configmap.yaml

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set grafana.service.type=LoadBalancer \
  --set grafana.adminPassword=admin
```

- Node Exporter автоматически встанут на все ноды
- В графане коннект к прометеусу: http://prometheus-operated:9090
- Из коробки в этом чарте сразу есть метрики кластера. В миникубе работают не все дэшборды

Кастомные мониторы для prometheus
```bash
kubectl apply -f prometheus-service-monitor.yaml 
```
В UI prometheus отобразится ServiceMonitor `vllm-backend-metrics`, но он будет пустой, пока не будет доступен эндопинт с метриками vllm