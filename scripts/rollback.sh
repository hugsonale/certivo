#!/bin/bash

#############################################################################
# Certivo Rollback Script
# Usage: ./scripts/rollback.sh [backup_timestamp]
#############################################################################

BACKUP_DIR="/opt/certivo/backups"
BACKUP_TIMESTAMP=$1

if [ -z "$BACKUP_TIMESTAMP" ]; then
    echo "❌ Error: Backup timestamp required"
    echo ""
    echo "Usage: ./scripts/rollback.sh TIMESTAMP"
    echo ""
    echo "Available backups:"
    ls -1 $BACKUP_DIR/certivo_backup_*.tar.gz 2>/dev/null | sed 's/.*certivo_backup_/  /' | sed 's/.tar.gz//'
    exit 1
fi

BACKUP_FILE="$BACKUP_DIR/certivo_backup_$BACKUP_TIMESTAMP.tar.gz"
DB_BACKUP="$BACKUP_DIR/certivo_v2.db.backup_$BACKUP_TIMESTAMP"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup not found: $BACKUP_FILE"
    exit 1
fi

echo "🔄 Rolling back to backup: $BACKUP_TIMESTAMP"

# Stop service
echo "⏸️  Stopping service..."
sudo systemctl stop certivo

# Restore files
echo "📦 Restoring files..."
cd /opt/certivo
tar -xzf $BACKUP_FILE

# Restore database
if [ -f "$DB_BACKUP" ]; then
    echo "🗄️  Restoring database..."
    cp $DB_BACKUP certivo_v2.db
fi

# Start service
echo "▶️  Starting service..."
sudo systemctl start certivo

echo "✅ Rollback complete!"

exit 0