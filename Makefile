.PHONY: help docker-build docker-push k8s-deploy k8s-delete local-up local-down

help:
	@echo "Certivo Deployment Commands"
	@echo "============================"
	@echo "make docker-build    - Build all Docker images"
	@echo "make docker-push     - Push images to registry"
	@echo "make k8s-deploy      - Deploy to Kubernetes"
	@echo "make k8s-delete      - Delete from Kubernetes"
	@echo "make local-up        - Start local Docker Compose"
	@echo "make local-down      - Stop local Docker Compose"

# Docker commands
docker-build:
	docker build -t certivo/api-gateway:latest services/api-gateway/
	docker build -t certivo/verification-api:latest services/verification-api/
	docker build -t certivo/challenge-service:latest services/challenge-service/
	docker build -t certivo/risk-scoring:latest services/risk-scoring/
	docker build -t certivo/async-worker:latest services/async-worker/
	docker build -t certivo/admin-service:latest services/admin-service/

docker-push:
	docker push certivo/api-gateway:latest
	docker push certivo/verification-api:latest
	docker push certivo/challenge-service:latest
	docker push certivo/risk-scoring:latest
	docker push certivo/async-worker:latest
	docker push certivo/admin-service:latest

# Kubernetes commands
k8s-deploy:
	kubectl apply -k infrastructure/kubernetes/

k8s-delete:
	kubectl delete -k infrastructure/kubernetes/

k8s-logs:
	kubectl logs -f -n certivo -l app=api-gateway

# Local development
local-up:
	docker-compose up -d

local-down:
	docker-compose down

local-logs:
	docker-compose logs -f