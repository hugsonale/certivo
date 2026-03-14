#!/bin/bash

#############################################################################
# Certivo Automated Backup Script
#
# Schedule with cron:
#   crontab -e
#   0 2 * * * /opt/certivo/scripts/backup.sh >> /var/log/certivo_backup.log 2>&1
#
# This runs daily at 2 AM
#############################################################################

set -e  # Exit on error

#############################################################################
# CONFIGURATION
#############################################################################

# Directories
BACKUP_DIR="/opt/certivo/backups"
APP_DIR="/opt/certivo"
LOGS_DIR="$APP_DIR/logs"

# Files
DB_FILE="$APP_DIR/certivo_v2.db"
ENV_FILE="$APP_DIR/.env"

# Retention (days)
RETENTION_DAYS=30

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_READABLE=$(date '+%Y-%m-%d %H:%M:%S')

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

#############################################################################
# FUNCTIONS
#############################################################################

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

#############################################################################
# START BACKUP
#############################################################################

log "Starting Certivo backup..."
log "Backup directory: $BACKUP_DIR"

# Create backup directory
mkdir -p $BACKUP_DIR

#############################################################################
# BACKUP DATABASE
#############################################################################

log "Backing up database..."

if [ -f "$DB_FILE" ]; then
    # Copy database
    cp "$DB_FILE" "$BACKUP_DIR/certivo_db_$TIMESTAMP.db"
    
    # Compress
    gzip "$BACKUP_DIR/certivo_db_$TIMESTAMP.db"
    
    DB_SIZE=$(du -h "$BACKUP_DIR/certivo_db_$TIMESTAMP.db.gz" | cut -f1)
    log "✓ Database backed up: certivo_db_$TIMESTAMP.db.gz ($DB_SIZE)"
else
    error "Database file not found: $DB_FILE"
fi

#############################################################################
# BACKUP LOGS
#############################################################################

log "Backing up logs..."

if [ -d "$LOGS_DIR" ]; then
    # Create tar archive of logs
    tar -czf "$BACKUP_DIR/certivo_logs_$TIMESTAMP.tar.gz" -C "$LOGS_DIR" . 2>/dev/null
    
    LOGS_SIZE=$(du -h "$BACKUP_DIR/certivo_logs_$TIMESTAMP.tar.gz" | cut -f1)
    log "✓ Logs backed up: certivo_logs_$TIMESTAMP.tar.gz ($LOGS_SIZE)"
else
    warning "Logs directory not found: $LOGS_DIR"
fi

#############################################################################
# BACKUP ENVIRONMENT FILE
#############################################################################

log "Backing up environment configuration..."

if [ -f "$ENV_FILE" ]; then
    # Copy .env (important for restore)
    cp "$ENV_FILE" "$BACKUP_DIR/certivo_env_$TIMESTAMP"
    
    # Encrypt it (optional - recommended for security)
    # openssl enc -aes-256-cbc -salt -in "$ENV_FILE" -out "$BACKUP_DIR/certivo_env_$TIMESTAMP.enc"
    
    log "✓ Environment file backed up"
else
    warning "Environment file not found: $ENV_FILE"
fi

#############################################################################
# BACKUP CONFIGURATION FILES
#############################################################################

log "Backing up configuration files..."

# Create archive of important configs
tar -czf "$BACKUP_DIR/certivo_config_$TIMESTAMP.tar.gz" \
    -C "$APP_DIR" \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='logs' \
    --exclude='backups' \
    --exclude='certivo_v2.db' \
    . 2>/dev/null

CONFIG_SIZE=$(du -h "$BACKUP_DIR/certivo_config_$TIMESTAMP.tar.gz" | cut -f1)
log "✓ Configuration backed up: certivo_config_$TIMESTAMP.tar.gz ($CONFIG_SIZE)"

#############################################################################
# DELETE OLD BACKUPS
#############################################################################

log "Cleaning up old backups (keeping last $RETENTION_DAYS days)..."

# Count backups before cleanup
BEFORE_COUNT=$(find $BACKUP_DIR -name "certivo_*" -type f | wc -l)

# Delete old database backups
find $BACKUP_DIR -name "certivo_db_*.db.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null

# Delete old log backups
find $BACKUP_DIR -name "certivo_logs_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null

# Delete old env backups
find $BACKUP_DIR -name "certivo_env_*" -mtime +$RETENTION_DAYS -delete 2>/dev/null

# Delete old config backups
find $BACKUP_DIR -name "certivo_config_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null

# Count backups after cleanup
AFTER_COUNT=$(find $BACKUP_DIR -name "certivo_*" -type f | wc -l)
DELETED=$((BEFORE_COUNT - AFTER_COUNT))

log "✓ Deleted $DELETED old backup files"

#############################################################################
# BACKUP SUMMARY
#############################################################################

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 BACKUP SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Timestamp:        $DATE_READABLE"
echo "Backup Location:  $BACKUP_DIR"
echo ""
echo "Backup Files Created:"
ls -lh $BACKUP_DIR/*$TIMESTAMP* 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
echo ""
echo "Total Backups:    $AFTER_COUNT files"
echo "Disk Usage:       $(du -sh $BACKUP_DIR | cut -f1)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

#############################################################################
# OPTIONAL: UPLOAD TO CLOUD STORAGE
#############################################################################

# Uncomment to upload to AWS S3
# log "Uploading to S3..."
# aws s3 cp "$BACKUP_DIR/certivo_db_$TIMESTAMP.db.gz" s3://your-bucket/backups/
# aws s3 cp "$BACKUP_DIR/certivo_config_$TIMESTAMP.tar.gz" s3://your-bucket/backups/

# Uncomment to upload to Dropbox
# log "Uploading to Dropbox..."
# /usr/local/bin/dropbox_uploader.sh upload "$BACKUP_DIR/certivo_db_$TIMESTAMP.db.gz" /backups/

#############################################################################
# BACKUP VERIFICATION
#############################################################################

log "Verifying backup integrity..."

# Test if database backup can be extracted
if gzip -t "$BACKUP_DIR/certivo_db_$TIMESTAMP.db.gz" 2>/dev/null; then
    log "✓ Database backup integrity verified"
else
    error "Database backup may be corrupted!"
fi

# Test if config backup can be extracted
if tar -tzf "$BACKUP_DIR/certivo_config_$TIMESTAMP.tar.gz" >/dev/null 2>&1; then
    log "✓ Config backup integrity verified"
else
    error "Config backup may be corrupted!"
fi

#############################################################################
# FINISH
#############################################################################

log "✅ Backup completed successfully!"

exit 0