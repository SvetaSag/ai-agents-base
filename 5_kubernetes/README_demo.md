# Kubernetes — сценарий live-demo

Пошаговый прогон занятия: поднять кластер → показать сущности → Ingress → ConfigMap/Secrets → мониторинг.
Локальные домены раскидываются по субдоменам через `/etc/hosts`.

**Нужно:** `minikube`, `kubectl`, `helm`, драйвер `qemu` (на macOS).

---

## 0. Старт кластера

```bash
make setup          # minikube: 3 ноды (qemu), аддоны ingress/metrics-server/dashboard, helm-репозитории
make update_hosts   # прописать *.hse-ai.ru на IP minikube в /etc/hosts
```

В отдельном терминале держим открытым туннель (нужен для Ingress / LoadBalancer):

```bash
minikube tunnel
```

> Проверка: `kubectl get nodes` → 3 ноды в статусе `Ready`.

---

## Part 1. Pod → Service → Ingress → ReplicaSet

```bash
cd part_1
minikube image load ubuntu:24.04

kubectl apply -f ubuntu_pod.yaml    # под-«зонд», из него будем ходить по сети
kubectl apply -f pod_1.yaml
kubectl apply -f pod_2.yaml
```

**Показать сеть подов** — заходим в ubuntu и дёргаем поды по их IP:

```bash
kubectl exec -it ubuntu -- bash
#   curl <POD_IP>        → отвечает nginx конкретного пода
```

**Service** — единая точка доступа по меткам:

```bash
kubectl apply -f service.yaml
#   из ubuntu: curl hse-service   → запросы балансируются между подами
```

**Ingress** — вход снаружи по домену:

```bash
kubectl apply -f ingress.yaml
#   в браузере: http://hse-ai.ru   → видим сайт
```

**ReplicaSet** — самовосстановление:

```bash
kubectl apply -f replicaset.yaml    # replicas: 4
```
- Теперь 4 пода (2 из Pod + ... из RS), на фронте прилетают разные страницы.
- Удаляем под → RS сразу поднимает новый.
- Меняем `replicas` в манифесте → число подов подстраивается.

---

## Part 2. Deployment: rollout, откат, nodeSelector

```bash
cd ../part_2
kubectl apply -f ingress.yaml       # добавляет backend.hse-ai.ru
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

**Обновление и откат:**

```bash
kubectl rollout history deployment/hse-deployment-2
# меняем образ в манифесте и apply → видим постепенную замену подов (RollingUpdate)
kubectl rollout undo deployment hse-deployment-2      # откат (файл манифеста не меняется)
```

**Размещение по нодам (метки + nodeSelector):**

```bash
kubectl get nodes --show-labels
kubectl label nodes minikube-m02 load=high
# раскомментируем nodeSelector в deployment.yaml и apply
kubectl apply -f deployment.yaml     # поды уезжают на ноду с меткой load=high
```

---

## Part 3. ConfigMap + Secrets

```bash
cd ../part_3
kubectl delete -f replicaset.yaml    # чистим RS из Part 1

kubectl apply -f configmap.yaml      # конфиг → монтируется в /etc/config
kubectl apply -f secrets.yaml        # секреты → пробрасываются в env

# base64 при необходимости:
echo -n 'admin'  | base64            # YWRtaW4=
echo -n 'secret' | base64            # c2VjcmV0

kubectl apply -f deployment.yaml
```

**Что показать:**
- Балансировка: из ubuntu `curl <SERVICE_IP> | grep Pod:` → имена подов разные.
- Secrets: заходим в под → переменные `USERNAME` / `PASSWORD` на месте.
- ConfigMap: в поде по пути `/etc/config` лежит наш конфиг.

---

## Part 4. Мониторинг (Prometheus + Grafana)

```bash
cd ../part_4_monitoring

kubectl create namespace monitoring
kubectl apply -f ingress-grafana.yaml
kubectl apply -f ingress-prometheus.yaml
kubectl apply -f grafana-dashboard-configmap.yaml

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set grafana.service.type=LoadBalancer \
  --set grafana.adminPassword=admin
```

**Что показать:**
- Node Exporter автоматически встаёт на все ноды.
- Grafana: http://grafana.hse-ai.ru (логин/пароль `admin` / `admin`), источник Prometheus — `http://prometheus-operated:9090`.
- Prometheus: http://prometheus.hse-ai.ru — метрики кластера из коробки (в minikube часть дашбордов пустые).

**Кастомный ServiceMonitor:**

```bash
kubectl apply -f prometheus-service-monitor.yaml
# в UI Prometheus появится ServiceMonitor vllm-backend-metrics
# (пустой, пока не поднят реальный эндпоинт /metrics vLLM)
```

**Снести мониторинг:**

```bash
helm uninstall prometheus -n monitoring       # удалить релиз (Prometheus, Grafana, exporters)

kubectl delete -f prometheus-service-monitor.yaml \
               -f grafana-dashboard-configmap.yaml \
               -f ingress-prometheus.yaml \
               -f ingress-grafana.yaml --ignore-not-found

kubectl delete namespace monitoring           # добить всё, что осталось в namespace
```

> `helm uninstall` по дизайну чарта **не удаляет CRD**. Если нужно вычистить и их:
> ```bash
> kubectl delete crd $(kubectl get crd -o name | grep monitoring.coreos.com)
> ```

### Альтернатива: весь стек через Helm (`values.yaml`)

Выше конфигурация размазана: `--set`-флаги + отдельные `kubectl apply` для ingress и dashboard.
Чище — держать всё в одном `values.yaml` и поднимать одним релизом.

`values.yaml`:

```yaml
grafana:
  adminPassword: admin
  service:
    type: LoadBalancer
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts: [grafana.hse-ai.ru]
  sidecar:
    dashboards:
      enabled: true          # сам подхватит ConfigMap с label grafana_dashboard: "1"

prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false   # видеть наши ServiceMonitor
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts: [prometheus.hse-ai.ru]
```

Поднять:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring

helm install prometheus prometheus-community/kube-prometheus-stack \
  -n monitoring -f values.yaml --version 65.1.1     # версию чарта пиним

# наш dashboard-configmap всё ещё нужен — grafana-sidecar его сам импортирует
kubectl apply -f grafana-dashboard-configmap.yaml
# кастомный ServiceMonitor приложения — тоже отдельно (это про наш сервис, не про чарт)
kubectl apply -f prometheus-service-monitor.yaml
```

Управление релизом:

```bash
helm upgrade prometheus prometheus-community/kube-prometheus-stack -n monitoring -f values.yaml
helm rollback prometheus 1 -n monitoring     # откат к предыдущей ревизии
helm uninstall prometheus -n monitoring      # снести весь стек одной командой
helm list -n monitoring                      # ревизии и статус релиза
```

**Почему так лучше, чем `kubectl apply` россыпью:**
- **Единый источник правды** — вся настройка в `values.yaml` вместо `--set` и 3-х отдельных манифестов; кладётся в git, ревьюится, воспроизводится один-в-один.
- **Upgrade / rollback одной командой** — Helm ведёт ревизии релиза; поменял values → `helm upgrade`, что-то сломал → `helm rollback`. С `kubectl apply` откат руками.
- **Чистое удаление** — `helm uninstall` убирает весь стек (Deployment'ы, Service, Ingress, CRD-инстансы). После `kubectl apply` пришлось бы удалять каждый ресурс вручную и что-то забыть.
- **Пиннинг версии чарта** (`--version`) → у всех одинаковый Prometheus/Grafana, нет «у меня работало».
- **Ingress и дашборды поднимает сам чарт** (grafana-sidecar) — меньше ручных yaml, меньше дрейфа конфигурации.

> Для live-demo можно показать оба пути: «руками» (нагляднее, что из чего состоит) → затем helm-native (как это делают в проде).

---

## Субдомены (локально, через /etc/hosts)

`make update_hosts` мапит на IP minikube:

| Домен | Назначение |
|---|---|
| `hse-ai.ru` | фронт (Part 1–3) |
| `backend.hse-ai.ru` | backend-сервис (Part 2) |
| `grafana.hse-ai.ru` | Grafana |
| `prometheus.hse-ai.ru` | Prometheus |
| `api / mlflow / kibana / argocd .hse-ai.ru` | зарезервированы под остальные сервисы |

---

## Бонус-демки (part_5 … part_10)

Короткие независимые демонстрации k8s-фич. Каждую можно показать отдельно; в конце — `kubectl delete -f <dir>`.

### Part 5. Автоскейлинг (HPA)

Поды сами масштабируются по нагрузке на CPU (работает `metrics-server`, включён в `make setup`).

```bash
cd part_5_autoscaling
kubectl apply -f deployment.yaml
kubectl apply -f hpa.yaml

# в отдельном терминале — следим за автоскейлером
kubectl get hpa php-apache --watch

# генерим нагрузку (в ещё одном терминале)
kubectl run -it --rm load --image=busybox --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://php-apache; done"
```
→ CPU растёт выше 50% → HPA поднимает реплики (до 5). Убираем нагрузку (`Ctrl-C`) → через пару минут схлопывается обратно к 1.

### Part 6. Health-checks (liveness / readiness)

```bash
cd ../part_6_probes
kubectl apply -f liveness.yaml
kubectl get pod liveness-demo --watch
```
→ Через ~30с файл удаляется, `livenessProbe` падает → kubelet перезапускает контейнер, растёт `RESTARTS`.

```bash
kubectl apply -f readiness.yaml
kubectl get pod readiness-demo
```
→ Пока `readinessProbe` не отдаёт 200, под `0/1` и не получает трафик; затем становится `1/1 Ready`.

### Part 7. Jobs и CronJobs

```bash
cd ../part_7_jobs
kubectl apply -f job.yaml
kubectl get jobs
kubectl logs job/hello-job     # выполняется 3 раза (completions: 3) и завершается

kubectl apply -f cronjob.yaml
kubectl get cronjob,jobs --watch   # раз в минуту создаётся новый Job
```

### Part 8. DaemonSet (по поду на каждую ноду)

```bash
cd ../part_8_daemonset
kubectl apply -f daemonset.yaml
kubectl get pods -o wide -l app=node-agent
```
→ Ровно 3 пода — по одному на `minikube`, `minikube-m02`, `minikube-m03`. Добавится нода — DaemonSet сам поднимет под и на ней.

### Part 9. Постоянное хранилище (PVC)

```bash
cd ../part_9_storage
kubectl apply -f pvc.yaml
kubectl get pvc               # STATUS=Bound
kubectl apply -f pod.yaml
kubectl logs storage-demo     # видим строку с датой в /data/log.txt

# удаляем под и поднимаем заново
kubectl delete pod storage-demo
kubectl apply -f pod.yaml
kubectl logs storage-demo     # старая строка на месте + добавилась новая → данные пережили под
```

### Part 10. Namespace + квоты (ResourceQuota / LimitRange)

```bash
cd ../part_10_namespace_quota
kubectl apply -f namespace.yaml
kubectl apply -f limitrange.yaml
kubectl apply -f resourcequota.yaml

# пробуем создать 5 подов при лимите 3
kubectl create deployment nginx --image=nginx --replicas=5 -n sandbox
kubectl get pods -n sandbox                 # поднялось только 3
kubectl describe quota sandbox-quota -n sandbox   # видно использование vs лимит
```
→ ReplicaSet упрётся в квоту: `kubectl get events -n sandbox` покажет `exceeded quota`.

**Убрать бонус-демки:**

```bash
kubectl delete -f part_5_autoscaling -f part_6_probes -f part_7_jobs \
               -f part_8_daemonset -f part_9_storage --ignore-not-found
kubectl delete namespace sandbox            # заодно снесёт всё из part_10
```

---

## Сборка образа (справочно, уже в Docker Hub)

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t aesedeu/nginx-hse-ai:1.0 -f Dockerfile --push .
```

## Cleanup

```bash
minikube delete      # снести кластер целиком
```
