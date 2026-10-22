# Занятие 4 — Kubernetes: мультиагентная система в кластере
.PHONY: setup hosts images secret clean

setup:   ## кластер: 3 ноды minikube на QEMU + аддоны ingress, metrics-server
	@./scripts/01_cluster.sh

hosts:   ## *.agents.test → IP кластера в /etc/hosts (нужен sudo)
	@./scripts/02_update_hosts.sh

images:  ## собрать образы агентов на всех нодах
	@./scripts/03_images.sh

secret:  ## ключ OpenRouter из .env → Secret llm-secret
	@./scripts/04_secret.sh

clean:   ## удалить кластер целиком
	minikube delete
