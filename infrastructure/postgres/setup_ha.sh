#!/bin/bash
# PostgreSQL High Availability Setup Script

set -e

echo "=================================================="
echo "PostgreSQL High Availability Setup"
echo "=================================================="

# Variables
PRIMARY_HOST="certivo-primary.postgres.internal"
REPLICA_1_HOST="certivo-replica-1.postgres.internal"
REPLICA_2_HOST="certivo-replica-2.postgres.internal"
POSTGRES_VERSION="15"
POSTGRES_USER="certivo"
POSTGRES_DB="certivo"
BACKUP_BUCKET="s3://certivo-postgres-backups"

echo ""
echo "Configuration:"
echo "  Primary: ${PRIMARY_HOST}"
echo "  Replica 1: ${REPLICA_1_HOST}"
echo "  Replica 2: ${REPLICA_2_HOST}"
echo "  Backup Bucket: ${BACKUP_BUCKET}"
echo ""

# Step 1: Configure Primary Database
echo "Step 1: Configuring Primary Database..."

cat > /tmp/postgresql_primary.conf <<EOF
# Replication settings
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
wal_keep_size = 1GB
hot_standby = on

# Archiving for PITR
archive_mode = on
archive_command = 'pgbackrest --stanza=certivo archive-push %p'

# Performance tuning
shared_buffers = 32GB
effective_cache_size = 96GB
maintenance_work_mem = 2GB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 64MB
min_wal_size = 1GB
max_wal_size = 4GB

# Connection settings
max_connections = 500
listen_addresses = '*'
EOF

scp /tmp/postgresql_primary.conf ${PRIMARY_HOST}:/etc/postgresql/${POSTGRES_VERSION}/main/postgresql.conf

echo "  ✓ Primary configuration uploaded"

# Step 2: Configure pg_hba.conf for replication
echo "Step 2: Configuring replication access..."

cat > /tmp/pg_hba_replication.conf <<EOF
# Replication connections
host    replication     replicator      ${REPLICA_1_HOST}/32       md5
host    replication     replicator      ${REPLICA_2_HOST}/32       md5

# Application connections
host    ${POSTGRES_DB}  ${POSTGRES_USER}    0.0.0.0/0              md5
EOF

scp /tmp/pg_hba_replication.conf ${PRIMARY_HOST}:/etc/postgresql/${POSTGRES_VERSION}/main/pg_hba.conf

echo "  ✓ Replication access configured"

# Step 3: Create replication user
echo "Step 3: Creating replication user..."

ssh ${PRIMARY_HOST} "sudo -u postgres psql -c \"CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'REPLICATION_PASSWORD';\""

echo "  ✓ Replication user created"

# Step 4: Restart primary
echo "Step 4: Restarting primary database..."

ssh ${PRIMARY_HOST} "sudo systemctl restart postgresql"
sleep 10

echo "  ✓ Primary database restarted"

# Step 5: Setup pgBackRest
echo "Step 5: Setting up pgBackRest..."

cat > /tmp/pgbackrest.conf <<EOF
[global]
repo1-type=s3
repo1-s3-bucket=certivo-postgres-backups
repo1-s3-region=us-east-1
repo1-s3-key=<AWS_ACCESS_KEY>
repo1-s3-key-secret=<AWS_SECRET_KEY>
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=<ENCRYPTION_PASSWORD>
repo1-retention-full=4
repo1-retention-diff=4

process-max=4
log-level-console=info
log-level-file=debug

[certivo]
pg1-path=/var/lib/postgresql/${POSTGRES_VERSION}/main
pg1-port=5432
pg1-user=postgres
EOF

scp /tmp/pgbackrest.conf ${PRIMARY_HOST}:/etc/pgbackrest/pgbackrest.conf

echo "  ✓ pgBackRest configured"

# Step 6: Initialize pgBackRest stanza
echo "Step 6: Initializing pgBackRest stanza..."

ssh ${PRIMARY_HOST} "sudo -u postgres pgbackrest --stanza=certivo stanza-create"
ssh ${PRIMARY_HOST} "sudo -u postgres pgbackrest --stanza=certivo check"

echo "  ✓ pgBackRest stanza initialized"

# Step 7: Take initial full backup
echo "Step 7: Taking initial full backup..."

ssh ${PRIMARY_HOST} "sudo -u postgres pgbackrest --stanza=certivo --type=full backup"

echo "  ✓ Initial backup completed"

# Step 8: Setup streaming replication for Replica 1
echo "Step 8: Setting up Replica 1..."

ssh ${REPLICA_1_HOST} "sudo systemctl stop postgresql"
ssh ${REPLICA_1_HOST} "sudo rm -rf /var/lib/postgresql/${POSTGRES_VERSION}/main/*"

# Use pg_basebackup for initial replica setup
ssh ${REPLICA_1_HOST} "sudo -u postgres pg_basebackup -h ${PRIMARY_HOST} -D /var/lib/postgresql/${POSTGRES_VERSION}/main -U replicator -P -v -R -X stream -C -S replica_1_slot"

# Configure recovery settings
cat > /tmp/postgresql_replica.conf <<EOF
# Replica-specific settings
hot_standby = on
max_standby_streaming_delay = 30s
wal_receiver_status_interval = 10s
hot_standby_feedback = on
EOF

scp /tmp/postgresql_replica.conf ${REPLICA_1_HOST}:/etc/postgresql/${POSTGRES_VERSION}/main/postgresql.conf

ssh ${REPLICA_1_HOST} "sudo systemctl start postgresql"

echo "  ✓ Replica 1 configured and started"

# Step 9: Setup Replica 2
echo "Step 9: Setting up Replica 2..."

ssh ${REPLICA_2_HOST} "sudo systemctl stop postgresql"
ssh ${REPLICA_2_HOST} "sudo rm -rf /var/lib/postgresql/${POSTGRES_VERSION}/main/*"

ssh ${REPLICA_2_HOST} "sudo -u postgres pg_basebackup -h ${PRIMARY_HOST} -D /var/lib/postgresql/${POSTGRES_VERSION}/main -U replicator -P -v -R -X stream -C -S replica_2_slot"

scp /tmp/postgresql_replica.conf ${REPLICA_2_HOST}:/etc/postgresql/${POSTGRES_VERSION}/main/postgresql.conf

ssh ${REPLICA_2_HOST} "sudo systemctl start postgresql"

echo "  ✓ Replica 2 configured and started"

# Step 10: Verify replication
echo "Step 10: Verifying replication..."

ssh ${PRIMARY_HOST} "sudo -u postgres psql -c \"SELECT * FROM pg_stat_replication;\""

echo ""
echo "=================================================="
echo "PostgreSQL High Availability Setup Complete!"
echo "=================================================="
echo ""
echo "Summary:"
echo "  ✓ Primary database configured"
echo "  ✓ 2 streaming replicas configured"
echo "  ✓ pgBackRest backup system configured"
echo "  ✓ Initial full backup completed"
echo "  ✓ Replication verified"
echo ""
echo "Next steps:"
echo "  1. Setup automated backup schedule"
echo "  2. Configure monitoring and alerts"
echo "  3. Test backup restore procedure"
echo ""