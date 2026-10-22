.PHONY: help build push deploy setup clean

# Переменные
DOCKERHUB_USERNAME ?= aesedeu
K8S_NAMESPACE ?= default

setup: ## Настроить Minikube и инфраструктуру
	@echo "Setting up Minikube"
	@./scripts/01_minikube.sh

update_hosts: ## Настроить Minikube и инфраструктуру
	@echo "Updating /etc/hosts..."
	@./scripts/02_update_hosts.sh