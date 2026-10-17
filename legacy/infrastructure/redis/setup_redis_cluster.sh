#!/bin/bash
# Redis Cluster Setup Script

set -e

echo "=================================================="
echo "Redis Cluster High Availability Setup"
echo "=================================================="

# Variables
REDIS_VERSION="7.2"
CLUSTER_NODES=(
    "redis-master-1.internal:6379"
    "redis-master-2.internal:6379"
    "redis-master-3.internal:6379"
    "redis-replica-1.internal:6379"
    "redis-replica-2.internal:6379"
    "redis-replica-3.internal:6379"
)

echo ""
echo "Configuration:"
echo "  Cluster Nodes: ${#CLUSTER_NODES[@]}"
echo "  Masters: 3"
echo "  Replicas per Master: 1"
echo ""

# Step 1: Install Redis on all nodes
echo "Step 1: Installing Redis on all nodes..."

for node in "${CLUSTER_NODES[@]}"; do
    host="${node%:*}"
    echo "  Installing on ${host}..."
    
    ssh ${host} << 'EOF'
        sudo apt-get update
        sudo apt-get install -y redis-server
        sudo systemctl enable redis-server
EOF
done

echo "  ✓ Redis installed on all nodes"

# Step 2: Configure each Redis node
echo "Step 2: Configuring Redis nodes..."

for node in "${CLUSTER_NODES[@]}"; do
    host="${node%:*}"
    port="${node#*:}"
    
    echo "  Configuring ${host}..."
    
    cat > /tmp/redis.conf <<EOF
# Network
bind 0.0.0.0
port ${port}
protected-mode no
tcp-backlog 511
timeout 300
tcp-keepalive 300

# General
daemonize yes
pidfile /var/run/redis/redis-server.pid
loglevel notice
logfile /var/log/redis/redis-server.log
databases 16

# Cluster
cluster-enabled yes
cluster-config-file nodes.conf
cluster-node-timeout 15000
cluster-replica-validity-factor 10
cluster-migration-barrier 1
cluster-require-full-coverage yes

# Persistence
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /var/lib/redis

# AOF
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Memory
maxmemory 16gb
maxmemory-policy allkeys-lru
maxmemory-samples 5

# Clients
maxclients 10000

# Replication
replica-serve-stale-data yes
replica-read-only yes
repl-diskless-sync no
repl-diskless-sync-delay 5
repl-disable-tcp-nodelay no
replica-priority 100

# Security
requirepass REDIS_PASSWORD
masterauth REDIS_PASSWORD

# Performance
hz 10
dynamic-hz yes
aof-rewrite-incremental-fsync yes
rdb-save-incremental-fsync yes
EOF

    scp /tmp/redis.conf ${host}:/etc/redis/redis.conf
    ssh ${host} "sudo systemctl restart redis-server"
done

echo "  ✓ Redis nodes configured"

# Step 3: Create Redis cluster
echo "Step 3: Creating Redis cluster..."

redis-cli --cluster create \
    redis-master-1.internal:6379 \
    redis-master-2.internal:6379 \
    redis-master-3.internal:6379 \
    redis-replica-1.internal:6379 \
    redis-replica-2.internal:6379 \
    redis-replica-3.internal:6379 \
    --cluster-replicas 1 \
    --cluster-yes \
    -a REDIS_PASSWORD

echo "  ✓ Redis cluster created"

# Step 4: Setup Redis Sentinel
echo "Step 4: Setting up Redis Sentinel..."

SENTINEL_NODES=(
    "redis-sentinel-1.internal"
    "redis-sentinel-2.internal"
    "redis-sentinel-3.internal"
)

for sentinel_host in "${SENTINEL_NODES[@]}"; do
    echo "  Configuring Sentinel on ${sentinel_host}..."
    
    cat > /tmp/sentinel.conf <<EOF
port 26379
daemonize yes
pidfile /var/run/redis/redis-sentinel.pid
logfile /var/log/redis/redis-sentinel.log
dir /var/lib/redis

# Monitor masters
sentinel monitor redis-master-1 redis-master-1.internal 6379 2
sentinel monitor redis-master-2 redis-master-2.internal 6379 2
sentinel monitor redis-master-3 redis-master-3.internal 6379 2

# Auth
sentinel auth-pass redis-master-1 REDIS_PASSWORD
sentinel auth-pass redis-master-2 REDIS_PASSWORD
sentinel auth-pass redis-master-3 REDIS_PASSWORD

# Failover settings
sentinel down-after-milliseconds redis-master-1 5000
sentinel down-after-milliseconds redis-master-2 5000
sentinel down-after-milliseconds redis-master-3 5000

sentinel parallel-syncs redis-master-1 1
sentinel parallel-syncs redis-master-2 1
sentinel parallel-syncs redis-master-3 1

sentinel failover-timeout redis-master-1 180000
sentinel failover-timeout redis-master-2 180000
sentinel failover-timeout redis-master-3 180000

# Notification scripts
sentinel notification-script redis-master-1 /etc/redis/notify.sh
sentinel notification-script redis-master-2 /etc/redis/notify.sh
sentinel notification-script redis-master-3 /etc/redis/notify.sh
EOF

    scp /tmp/sentinel.conf ${sentinel_host}:/etc/redis/sentinel.conf
    
    # Create notification script
    cat > /tmp/notify.sh <<'EOF'
#!/bin/bash
# Sentinel notification script
EVENT_TYPE=$1
EVENT_NAME=$2
shift 2
EVENT_DATA="$@"

# Send alert
curl -X POST https://alerts.certivo.com/redis/sentinel \
  -H "Content-Type: application/json" \
  -d "{
    \"event_type\": \"${EVENT_TYPE}\",
    \"event_name\": \"${EVENT_NAME}\",
    \"data\": \"${EVENT_DATA}\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }"
EOF

    scp /tmp/notify.sh ${sentinel_host}:/etc/redis/notify.sh
    ssh ${sentinel_host} "chmod +x /etc/redis/notify.sh"
    
    # Start sentinel
    ssh ${sentinel_host} "redis-sentinel /etc/redis/sentinel.conf"
done

echo "  ✓ Redis Sentinel configured"

# Step 5: Verify cluster
echo "Step 5: Verifying cluster..."

redis-cli -c -h redis-master-1.internal -p 6379 -a REDIS_PASSWORD cluster info
redis-cli -c -h redis-master-1.internal -p 6379 -a REDIS_PASSWORD cluster nodes

echo ""
echo "=================================================="
echo "Redis Cluster High Availability Setup Complete!"
echo "=================================================="
echo ""
echo "Summary:"
echo "  ✓ 6-node Redis cluster created (3 masters + 3 replicas)"
echo "  ✓ Redis Sentinel configured for automatic failover"
echo "  ✓ Persistence enabled (RDB + AOF)"
echo "  ✓ Memory policy: allkeys-lru"
echo ""
echo "Cluster endpoints:"
echo "  redis-master-1.internal:6379"
echo "  redis-master-2.internal:6379"
echo "  redis-master-3.internal:6379"
echo ""
echo "Sentinel endpoints:"
echo "  redis-sentinel-1.internal:26379"
echo "  redis-sentinel-2.internal:26379"
echo "  redis-sentinel-3.internal:26379"
echo ""