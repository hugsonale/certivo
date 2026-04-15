# Certivo Microservices Architecture

Production-grade microservices deployment for Certivo human verification system

## Architecture

- **API Gateway**: Edge layer with WAF, rate limiting, bot detection
- **Verification API**: Stateless video processing service
- **Challenge Service**: Nonce generation and challenge lifecycle
- **Risk Scoring**: ML-based trust analysis
- **Async Worker**: Background video processing
- **Admin Service**: Isolated administrative interface

## Deployment

### Local Development (Docker Compose)

```bash
# Start all services
make local-up

# View logs
make local-logs

# Stop all services
make local-down
```

### Production (Kubernetes)

```bash
# Build images
make docker-build

# Push to registry
make docker-push

# Deploy to K8s
make k8s-deploy

# View logs
make k8s-logs
```

## Horizontal Scaling

All services support horizontal autoscaling:

- **API Gateway**: 3-10 replicas (CPU: 70%, Memory: 80%)
- **Verification API**: 2-20 replicas (CPU: 70%, Memory: 80%)
- **Challenge Service**: 2-10 replicas (CPU: 70%)
- **Risk Scoring**: 2-10 replicas (CPU: 70%, Memory: 80%)
- **Async Worker**: 3-20 replicas (CPU: 75%, Memory: 85%)

## Security

- ✅ Inter-service authentication via `INTERNAL_AUTH_TOKEN`
- ✅ TLS encryption for all inter-service traffic
- ✅ Network policies isolating admin service
- ✅ Secrets management via Kubernetes Secrets
- ✅ IP-based access control for admin panel

## Monitoring

- Prometheus metrics at `/metrics` on all services
- Grafana dashboards at `http://localhost:3000`