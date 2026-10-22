# Занятие 4 — Kubernetes: разворачиваем мультиагентную систему

В занятиях 1–3 агенты жили в блокнотах и терминалах на ноутбуке. Теперь разворачиваем
**банковскую мультиагентную систему из занятия 3 в кластере Kubernetes**: каждый агент —
отдельный сервис со своими репликами, адресом, настройками и проверками здоровья.

```
                    Ingress  risk.agents.test
 ноутбук ─────────────────────────┐
                                  ▼
                       ⚖️ risk-manager  ×1→2      ── A2A ──▶  📊 analyst  ×2→4  ── MCP ──▶  🔧 bank-mcp  ×2
                       (решает по кредиту,                    (SQL-аналитика,             (инструменты
                        помнит разговор)                       без памяти)                 банка)
                                  │                                                           │
                                  └──────── память (часть 7) ──▶ 🗄 bank-db (Postgres + том) ◀─┘
```

Формат: **лекция (презентация `lecture/`) + практика сразу в кластере**. Идём от простого к
сложному: сначала основы Kubernetes на игрушечном агенте, потом настоящие агенты.

| Часть | Тема | Что делаем |
|---|---|---|
| 0 | Кластер | 3 ноды minikube на QEMU, образы агентов |
| 1 | Pod | запускаем агентов-подов, ходим к ним по IP |
| 2 | Service + Ingress | один адрес на всех агентов, балансировка, вход снаружи по домену |
| 3 | ReplicaSet + Deployment | самовосстановление, масштабирование, обновление v1 → v2, откат, nodeSelector |
| 4 | ConfigMap + Secret | настройки и ключ API агента — отдельно от образа |
| 5 | База в кластере | PersistentVolumeClaim, Postgres, Job загрузки данных, initContainer |
| 6 | **Мультиагентная система** | MCP-сервер + аналитик + риск-менеджер, пробы здоровья, Ingress |
| 7 | **Масштабирование и состояние** | 4 аналитика; почему риск-менеджер «забывает» на 2 репликах и как это лечится |
| 8 | Бонус | агент по расписанию (CronJob), DaemonSet, автоскейлинг (HPA), liveness, песочница с квотами |
| 9 | Бонус | мониторинг: Prometheus + Grafana, дашборд «Агенты в кластере» |

Части 1–4 — на **hello-agent**: крошечный «агент» без LLM (один файл на Python), отвечает,
кто он и на каком поде/ноде запущен. Части 5–9 — на **настоящих агентах** из занятия 3
(образ `bank-agents`: MCP-сервер, аналитик, риск-менеджер, загрузчик данных).

--- 

## Часть 0. Кластер

**Нужно (macOS):** `brew install minikube kubectl helm qemu socket_vmnet` и один раз запустить
сетевой демон для QEMU (спросит пароль):

```bash
sudo brew services start socket_vmnet
```

```bash
cp .env.example .env     # вписать OPENROUTER_API_KEY
make setup               # 3 ноды minikube на QEMU (2 CPU, 4 ГБ, 20 ГБ каждая) + ingress, metrics-server  ~3 мин
make images              # собрать образы прямо в кластере, на всех нодах                               ~5 мин
make hosts               # agents.test, risk.agents.test, grafana/prometheus.agents.test → IP кластера (sudo)
make secret              # ключ OpenRouter из .env → Secret llm-secret
uv sync                  # клиент на ноутбуке (для блокнота agents_client.ipynb)
```

```bash
kubectl get nodes -o wide          # 3 ноды Ready: minikube (control plane), minikube-m02, minikube-m03
minikube image ls | grep -E "hello-agent|bank-agents"
```

> С QEMU + socket_vmnet IP кластера (`minikube ip`) доступен с ноутбука напрямую, поэтому
> Ingress работает **без** `minikube tunnel`. Туннель нужен только для Service типа LoadBalancer.

---

## Часть 1. Pod — один запущенный агент

```bash
kubectl apply -f part_1_pods/ubuntu.yaml          # под-«зонд», из него ходим по сети кластера
kubectl apply -f part_1_pods/agent-pod-1.yaml -f part_1_pods/agent-pod-2.yaml
kubectl get pods -o wide                          # у каждого пода свой IP и своя нода
```

Заходим в зонд и обращаемся к агенту **по IP пода** (подставьте IP из `get pods -o wide`):

```bash
kubectl exec -it ubuntu -- sh
  curl <IP_пода>:8080            # {"agent": "hello-agent", "pod": "agent-pod-1", "node": "minikube-m03", ...}
```

**Что видим:** поды на разных нодах видят друг друга по IP — у кластера общая сеть.
**Проблема:** IP пода меняется при каждом перезапуске — на него нельзя опираться.

---

## Часть 2. Service + Ingress — постоянный адрес и вход снаружи

```bash
kubectl apply -f part_2_service_ingress/service.yaml
kubectl exec ubuntu -- curl -s hello-agent       # по ИМЕНИ сервиса (DNS кластера)
```

Повторите несколько раз — `"pod"` меняется: Service **балансирует** запросы между всеми подами с
меткой `app: hello-agent`.

```bash
kubectl apply -f part_2_service_ingress/ingress.yaml
curl http://agents.test                          # с ноутбука, по домену (make hosts)
```

---

## Часть 3. ReplicaSet и Deployment

**ReplicaSet — «всегда держи 4 агента»:**

```bash
kubectl apply -f part_3_deployment/replicaset.yaml
kubectl get pods -l app=hello-agent              # 4 пода: 2 «голых» пода из части 1 он забрал себе + 2 новых
kubectl delete pod agent-pod-1                   # удалили — сразу появился новый
kubectl scale rs hello-agent-rs --replicas=2     # лишние удаляются
kubectl delete rs hello-agent-rs; kubectl delete pod agent-pod-2 --ignore-not-found
```

**Deployment — обновления без простоя и откат:**

```bash
kubectl apply -f part_3_deployment/deployment.yaml
kubectl rollout status deploy/hello-agent
kubectl exec ubuntu -- curl -s hello-agent | grep version      # "1"

kubectl set image deploy/hello-agent agent=hello-agent:2      # новая версия агента
kubectl get pods -l app=hello-agent -w                          # поды меняются по одному (Ctrl-C)
kubectl exec ubuntu -- curl -s hello-agent | grep version       # "2"
kubectl rollout history deploy/hello-agent
kubectl rollout undo deploy/hello-agent                         # откат на версию 1
```

> `maxUnavailable: 0, maxSurge: 1` — сначала поднимается новый под, и только когда он готов,
> гасится старый. Чтобы агент **действительно** отвечал всё время, в манифесте ещё два блока:
> `readinessProbe` (новый под получает трафик, только когда уже слушает порт) и `preStop`
> (старый под ещё 5 с отвечает, пока Service убирает его из балансировки). Без них при каждой
> выкатке теряется несколько запросов — проверено: 1–4 ошибки на ~400 запросов, с ними — 0.

**Размещение по нодам (метки + nodeSelector):**

```bash
kubectl get nodes --show-labels
kubectl label nodes minikube-m02 load=high
# в part_3_deployment/deployment.yaml раскомментировать nodeSelector, затем:
kubectl apply -f part_3_deployment/deployment.yaml
kubectl get pods -l app=hello-agent -o wide                     # все поды уехали на minikube-m02
```

Убираем за собой (часть 4 создаст Deployment заново):

```bash
kubectl delete -f part_3_deployment/deployment.yaml
kubectl label nodes minikube-m02 load-
```

> **Типичная ошибка.** Сняли метку с ноды, а `nodeSelector` в Deployment остался → новые поды
> висят в `Pending`, а `kubectl describe pod` пишет `didn't match Pod's node affinity/selector`.

---

## Часть 4. ConfigMap и Secret — настройки отдельно от образа

```bash
kubectl apply -f part_4_config_secrets/
kubectl exec ubuntu -- curl -s hello-agent
#   "agent": "support-agent", "greeting": "Здравствуйте! Я агент поддержки…",
#   "config_file": "model: openai/gpt-4o-mini …", "api_key_set": true
```

Тот же образ `hello-agent:1` стал другим агентом — поменялись только настройки:

```bash
kubectl exec deploy/hello-agent -- sh -c 'echo $AGENT_NAME; echo $API_KEY; cat /etc/agent/config.yaml'
kubectl get secret hello-agent-secret -o jsonpath='{.data.API_KEY}' | base64 -d     # base64 — НЕ шифрование
```

- **ConfigMap** — несекретное: имя, приветствие, конфиг (как переменные окружения и как файл `/etc/agent/config.yaml`);
- **Secret** — ключи и пароли. В манифестах — base64, это **кодирование, а не шифрование**: доступ к
  секретам закрывают правами (RBAC), а в проде хранят во внешнем хранилище (Vault и т. п.).

> Переменные окружения из ConfigMap/Secret читаются **при старте пода**. Поменяли значение →
> `kubectl rollout restart deploy/<имя>`, иначе запущенные поды живут со старым.


---

## Часть 5. База банка в кластере: том, Postgres, Job

```bash
kubectl apply -f part_5_bank_db/secret.yaml -f part_5_bank_db/init-sql.yaml -f part_5_bank_db/postgres.yaml
kubectl get pvc                                   # bank-db-data  Bound
kubectl apply -f part_5_bank_db/seed-job.yaml     # загрузка датасета (тот же, что в занятиях 2–3)
kubectl get pods -l job-name=bank-seed -w         # Init:0/1 → PodInitializing → Completed
kubectl logs job/bank-seed -c wait-for-db         # initContainer: «жду базу…»
kubectl logs job/bank-seed                        # ✓ bank database ready  (~40 с, без интернета — данные в образе)
```

| Сущность | Зачем |
|---|---|
| **PersistentVolumeClaim** | «мне нужен диск на 2 ГБ» — данные переживают перезапуск пода |
| **Deployment `bank-db`** | `replicas: 1` и `strategy: Recreate`: в один том пишет только один Postgres |
| **ConfigMap `bank-db-init`** | `init.sql` — роль `mcp_reader` только для чтения + база `agent` для части 7 |
| **Job `bank-seed`** | «выполнить и завершиться»; `initContainers` ждёт, пока база поднимется |

Проверка, что данные переживают под:

```bash
kubectl delete pod -l app=bank-db
kubectl exec deploy/bank-db -- psql -U postgres -d bank -tAc "select count(*) from transactions"   # 1056320
```

> Том minikube — папка на диске **конкретной ноды**, поэтому база привязана к ноде `minikube`
> (`nodeSelector`). В облаке тома сетевые, и такая привязка не нужна.

---

## Часть 6. Мультиагентная система

```bash
kubectl apply -f part_6_agents/                   # ConfigMap + MCP-сервер + аналитик + риск-менеджер + Ingress
kubectl get pods -o wide -l 'app in (bank-mcp,analyst,risk-manager)'
kubectl logs -f -l app=analyst --prefix           # ⏳ жду MCP-сервер… → analyst is ready
```

Каждый агент — Deployment + Service. Агенты находят друг друга **по именам сервисов**
(`http://bank-mcp:8101/mcp`, `http://analyst:8102`) — это настройки в ConfigMap `agents-config`.

**Спрашиваем изнутри кластера** (одноразовый под с нашим клиентом `ask.py`):

```bash
kubectl run ask --rm -it --restart=Never --image=bank-agents:1 -- \
  python ask.py http://risk-manager:8103 "Можно ли выдать счёту 2378 кредит 150 000 CZK на 24 месяца?"
```

**Спрашиваем с ноутбука** через Ingress — блокнот `agents_client.ipynb` или:

```bash
uv run python images/agents/ask.py http://risk.agents.test "Можно ли выдать счёту 1583 кредит 300 000 CZK на 36 месяцев?"
```

Во время ответа смотрите логи — видно, какой под что делает:

```bash
kubectl logs -f -l app=risk-manager --prefix      # ❓ вопрос → 📨 вопросы аналитику → ⚖️ решение
kubectl logs -f -l app=analyst --prefix           # какой из аналитиков отвечает
kubectl logs -f -l app=bank-mcp --prefix          # 🔧 SQL — по двум репликам MCP
```

| Что в манифестах | Зачем |
|---|---|
| один образ, разные `command:` | MCP-сервер, аналитик, риск-менеджер и загрузчик — один образ `bank-agents:1` |
| `startupProbe` (аналитик) | даём до 2,5 мин на старт (ждёт MCP-сервер); пока идёт — liveness не убивает под |
| `readinessProbe` | трафик на под — только когда он готов (карточка агента отвечает) |
| `livenessProbe` | агент перестал отвечать → перезапуск |
| `PUBLIC_URL` | адрес в A2A-карточке: аналитик — `http://analyst:8102/`, риск-менеджер — внешний `http://risk.agents.test/` |
| Ingress только у риск-менеджера | аналитик и MCP снаружи **не видны** — к ним ходят только агенты внутри кластера |
| `proxy-read-timeout: 300` | агент думает дольше 60 с (таймаут nginx по умолчанию) |

**Что сломалось бы без этих деталей** (всё проверено на этом кластере):

- **MCP-сессия и балансировщик.** MCP по HTTP по умолчанию хранит сессию на реплике сервера. С двумя
  репликами за одним Service `initialize` уходит в одну, а следующий запрос — в другую, которая про
  сессию не знает: **18 из 20** вызовов падали с `Session terminated`. Лечится `stateless_http=True`
  в `mcp_server.py` — каждая реплика отвечает на любой запрос.
- **Два адреса одного агента.** Карточка риск-менеджера содержит внешний адрес `risk.agents.test`,
  а внутри кластера такого имени нет. Поэтому `ask.py` отправляет сообщение туда, откуда взял
  карточку (`http://risk-manager:8103` внутри, `http://risk.agents.test` снаружи).
- **PID 1 и SIGTERM.** Python в контейнере — процесс №1 и по умолчанию игнорирует сигнал остановки:
  каждый под гасился бы 30 с. В `hello-agent` обработка SIGTERM добавлена явно (uvicorn у агентов
  делает это сам).
- **Запросы во время выкатки.** Под, который быстро останавливается, успевает закрыть порт раньше,
  чем сетевые правила кластера перестанут на него слать трафик, а новый под без `readinessProbe`
  получает запросы раньше, чем начал слушать. Поэтому у всех Deployment'ов есть `readinessProbe` и
  `preStop: sleep 5`.
- **Агенты думают долго.** При остановке пода Kubernetes по умолчанию ждёт 30 с и убивает его, а
  решение риск-менеджера (несколько вызовов LLM и аналитиков) идёт и дольше — запрос обрывался с
  `Server disconnected`. У аналитика и риск-менеджера `terminationGracePeriodSeconds: 120`: начатые
  запросы доделываются (проверено: перезапуск обоих посреди трёх решений — все три дошли, самое долгое 54 с).

---

## Часть 7. Масштабирование и состояние

**Агенты без состояния размножаются свободно:**

```bash
kubectl scale deploy/analyst --replicas=4
kubectl get pods -l app=analyst -o wide           # 4 аналитика на 3 нодах
kubectl top pods                                  # CPU почти ноль — агенты ждут LLM, а не считают
```

> Поэтому автоскейлинг по CPU (часть 8) агентам **не подходит**: их масштабируют по числу запросов
> или длине очереди (например, KEDA).

**Агент с памятью — нет.** Риск-менеджер помнит разговор в RAM своего пода. Две реплики:

```bash
kubectl scale deploy/risk-manager --replicas=2
```

В блокноте `agents_client.ipynb` (раздел «Память») задаём вопрос, а потом уточнения в **том же
разговоре**: ответы приходят то от одного пода (он помнит счёт), то от другого (`НЕ ЗНАЮ`).
Ingress раскидывает запросы по подам, а память у каждого своя.

**Лечим: выносим память из подов в Postgres** (база `agent` из части 5):

```bash
kubectl apply -f part_7_scale_state/risk-manager-shared-memory.yaml     # + CHECKPOINT_DSN
kubectl get pods -l app=risk-manager -w        # дождитесь, пока старые поды (память в RAM) исчезнут, Ctrl-C
kubectl logs -l app=risk-manager | grep ready                           # memory: Postgres
```

Повторяем эксперимент — **любая** реплика продолжает **любой** разговор, а разговор переживает даже
удаление всех подов (`kubectl delete pod -l app=risk-manager`).

> Правило: **поды — одноразовые**. Всё, что должно жить дольше пода (память агентов, файлы, сессии),
> хранится вне его — в базе, хранилище, кэше.

---

## Часть 8. Бонус — ещё сущности Kubernetes на агентах

```bash
# CronJob — агент по расписанию: раз в 2 минуты спрашивает аналитика и печатает «отчёт»
kubectl apply -f part_8_bonus/cronjob-report.yaml
kubectl get cronjob,jobs                          # каждые 2 минуты — новый Job
kubectl logs job/<имя Job из списка>              # Всего кредитов в банке: 682, из них running_in_debt: 45
kubectl delete -f part_8_bonus/cronjob-report.yaml   # не забыть: каждый запуск тратит токены

# DaemonSet — по одному агенту на КАЖДОЙ ноде (сборщики логов, агенты мониторинга)
kubectl apply -f part_8_bonus/daemonset.yaml
kubectl get pods -l app=node-agent -o wide        # ровно 3 пода, по одному на ноду

# liveness — агент «ломается» через 30 с, kubelet его перезапускает
kubectl apply -f part_8_bonus/liveness.yaml
kubectl get pod flaky-agent -w                    # RESTARTS растёт; kubectl describe pod flaky-agent → Liveness probe failed

# HPA — автоскейлинг по CPU
kubectl apply -f part_8_bonus/hpa.yaml
kubectl get hpa busy-agent -w                     # (в отдельном терминале)
kubectl run load --rm -it --restart=Never --image=curlimages/curl:8.11.1 -- \
  sh -c "while true; do curl -s busy-agent/work >/dev/null; done"
#   → CPU выше 50% → через ~1 мин реплик 3–5; Ctrl-C → через ~5 мин схлопывается до 1

# Namespace + квоты — песочница для экспериментальных агентов
kubectl apply -f part_8_bonus/sandbox.yaml
kubectl create deployment exp-agent --image=hello-agent:1 --replicas=5 -n sandbox
kubectl get deploy -n sandbox                     # 3/5: квота — 3 пода
kubectl get events -n sandbox | grep quota        # exceeded quota: sandbox-quota
```

Убрать: `kubectl delete -f part_8_bonus/ --ignore-not-found` (namespace `sandbox` удалится вместе со всем внутри).

---

## Часть 9. Бонус — мониторинг: Prometheus + Grafana

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update prometheus-community       # только этот репозиторий: один недоступный из других роняет общий update
kubectl create namespace monitoring
helm install prometheus prometheus-community/kube-prometheus-stack \
  -n monitoring -f part_9_monitoring/values.yaml --version 65.1.1 --wait     # ~1–2 мин
kubectl apply -f part_9_monitoring/agents-dashboard.yaml                     # наш дашборд
```

- **Grafana:** http://grafana.agents.test (admin / admin) → дашборд **«Агенты в кластере»**: память и CPU
  подов агентов, готовые реплики, перезапуски. Попробуйте `kubectl scale` и liveness из части 8 — видно сразу;
- **Prometheus:** http://prometheus.agents.test — сырые метрики и PromQL;
- node-exporter встал на каждую ноду сам — это тоже DaemonSet.

> В minikube cAdvisor отдаёт метрики подов без метки `container`, поэтому часть стандартных
> дашбордов («Compute Resources / Pod» и т. п.) пустая. В нашем дашборде запросы без этого фильтра.

Вся настройка стека — в одном `values.yaml`: `helm upgrade … -f values.yaml` применит изменения,
`helm rollback prometheus 1 -n monitoring` откатит, `helm uninstall prometheus -n monitoring` удалит всё.

---

## Уборка

```bash
kubectl delete -f part_8_bonus/ --ignore-not-found
helm uninstall prometheus -n monitoring; kubectl delete namespace monitoring
make clean                                        # удалить кластер целиком (minikube delete)
```

## Файлы

```
Makefile, scripts/          кластер, /etc/hosts, сборка образов, Secret с ключом
images/hello-agent/         игрушечный агент для частей 1–4 (один файл, без зависимостей)
images/agents/              настоящие агенты из занятия 3 — образ bank-agents:1
  mcp_server.py               MCP-сервер банка (stateless — для нескольких реплик)
  analyst_agent.py            аналитик (A2A, без памяти)
  risk_agent.py               риск-менеджер (A2A, память в RAM или Postgres)
  ask.py                      клиент A2A: вопрос из терминала, из пода, из CronJob
  scripts/load_berka.py, data/   загрузчик и кэш датасета
part_1_pods … part_9_monitoring/   манифесты по частям
agents_client.ipynb         разговор с агентами с ноутбука (части 6–7)
lecture/                    презентация
```
