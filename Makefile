.PHONY: help docker-build docker-push k8s-deploy k8s-delete local-up local-down


.PHONY: help test contract-tests validate-openapi api-docs


.PHONY: help test-rate-limits test-distributed manual-rate-test


.PHONY: test-entropy test-red-team validate-entropy

.PHONY: test-security validate-replay-resistance

help:
	@echo "Certivo Rate Limiting Commands"
	@echo "=============================="
	@echo "make test-rate-limits      - Run rate limiting tests"
	@echo "make test-distributed      - Test distributed enforcement"
	@echo "make manual-rate-test      - Manual rate limit testing"
	@echo "make bypass-metrics        - Show bypass attempt metrics"


help:
	@echo "Certivo API Commands"
	@echo "==================="
	@echo "make test              - Run all tests"
	@echo "make contract-tests    - Run API contract tests"
	@echo "make validate-openapi  - Validate OpenAPI specification"
	@echo "make api-docs          - Generate API documentation"
	@echo "make check-coverage    - Check OpenAPI coverage"

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


# Testing
test: contract-tests

contract-tests:
	pytest tests/contract/ -v

# OpenAPI validation
validate-openapi:
	openapi-spec-validator api/openapi.yaml

# API documentation
api-docs:
	./scripts/generate_api_docs.sh

# Coverage check
check-coverage:
	python scripts/check_openapi_coverage.py

# Run all checks (for CI)
ci-checks: validate-openapi check-coverage contract-tests
	@echo "✅ All CI checks passed"


# Rate limiting tests
test-rate-limits:
	pytest tests/integration/test_rate_limiting.py -v

test-distributed:
	pytest tests/integration/test_distributed_consistency.py -v

manual-rate-test:
	python scripts/test_rate_limits.py

bypass-metrics:
	curl http://localhost:8000/metrics/bypass-attempts | jq


# Entropy testing
test-entropy:
	pytest tests/red_team/test_prerecorded_attacks.py::TestEntropyValidation -v

test-red-team:
	pytest tests/red_team/ -v

validate-entropy:
	python scripts/validate_entropy.py

# Combined validation
validate-all: validate-entropy test-red-team
	@echo "✅ All entropy and red team tests passed"

# Security testing
test-security:
	pytest tests/security/ -v

validate-replay-resistance:
	python scripts/validate_replay_resistance.py

# Complete validation
validate-all: validate-replay-resistance test-security
	@echo "✅ All replay resistance validations passed"


.PHONY: test-liveness test-deepfake check-far-frr validate-liveness

# Liveness testing
test-liveness:
	pytest tests/unit/test_liveness_detection.py -v

test-deepfake:
	pytest tests/red_team/test_deepfake_resistance.py -v

check-far-frr:
	python scripts/check_far_frr_compliance.py

validate-liveness: test-liveness test-deepfake check-far-frr
	@echo "✅ All liveness and deepfake resistance tests passed"