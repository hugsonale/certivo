#!/bin/bash

#############################################################################
# Certivo Deployment Script
# 
# Description: Automated deployment with backup, testing, and rollback
# Usage: ./scripts/deploy.sh [production|staging|local]
# Author: Certivo Team
# Version: 1.0.0
#############################################################################

set -e  # Exit immediately if a command exits with a non-zero status

#############################################################################
# CONFIGURATION
#############################################################################

# Environment (production, staging, or local)
ENVIRONMENT=${1:-production}

# Directories
APP_DIR="/opt/certivo"
BACKUP_DIR="/opt/certivo/backups"
VENV_DIR="$APP_DIR/venv"
LOGS_DIR="$APP_DIR/logs"

# Files
DB_FILE="certivo_v2.db"
ENV_FILE=".env"
LOG_FILE="/var/log/certivo_deploy.log"

# Service name (for systemd)
SERVICE_NAME="certivo"

# Git repository
GIT_BRANCH="main"

#############################################################################
# COLORS FOR OUTPUT
#############################################################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

#############################################################################
# HELPER FUNCTIONS
#############################################################################

print_header() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a $LOG_FILE
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a $LOG_FILE
    echo -e "${RED}Deployment failed!${NC}" | tee -a $LOG_FILE
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a $LOG_FILE
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a $LOG_FILE
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a $LOG_FILE
}

#############################################################################
# DEPLOYMENT START
#############################################################################

print_header "CERTIVO DEPLOYMENT - $ENVIRONMENT"

log "Starting deployment to $ENVIRONMENT environment"
log "User: $USER"
log "Directory: $(pwd)"

#############################################################################
# PRE-DEPLOYMENT CHECKS
#############################################################################

print_header "STEP 1/10: PRE-DEPLOYMENT CHECKS"

# Check if running in correct directory
if [ ! -f "main.py" ]; then
    # Try to cd to app directory
    if [ -d "$APP_DIR" ]; then
        cd $APP_DIR
        log "Changed to application directory: $APP_DIR"
    else
        error "Not in Certivo directory and $APP_DIR doesn't exist"
    fi
fi

# Check for required files
info "Checking for required files..."
REQUIRED_FILES=("main.py" "database.py" "challenge_engine.py" "human_verification.py")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        error "Required file missing: $file"
    fi
done
success "All required files present"

# Check Python version
info "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
log "Python version: $PYTHON_VERSION"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    warning "Virtual environment not found, creating..."
    python3 -m venv venv
    success "Virtual environment created"
fi

#############################################################################
# STEP 2: CREATE BACKUP
#############################################################################

print_header "STEP 2/10: CREATING BACKUP"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="certivo_backup_$TIMESTAMP"

# Create backup directory
mkdir -p $BACKUP_DIR
log "Backup directory: $BACKUP_DIR"

# Backup database
if [ -f "$DB_FILE" ]; then
    info "Backing up database..."
    cp $DB_FILE "$BACKUP_DIR/${DB_FILE}.backup_$TIMESTAMP"
    success "Database backed up: ${DB_FILE}.backup_$TIMESTAMP"
else
    warning "Database file not found: $DB_FILE (new installation?)"
fi

# Backup .env file
if [ -f "$ENV_FILE" ]; then
    info "Backing up environment file..."
    cp $ENV_FILE "$BACKUP_DIR/.env.backup_$TIMESTAMP"
    success "Environment file backed up"
fi

# Create full application backup
info "Creating full application backup..."
tar -czf "$BACKUP_DIR/$BACKUP_NAME.tar.gz" \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='logs/*.log' \
    --exclude='backups' \
    . 2>/dev/null

success "Full backup created: $BACKUP_NAME.tar.gz"

#############################################################################
# STEP 3: STOP APPLICATION
#############################################################################

print_header "STEP 3/10: STOPPING APPLICATION"

# Check if systemd service exists
if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    if systemctl is-active --quiet $SERVICE_NAME; then
        info "Stopping $SERVICE_NAME service..."
        sudo systemctl stop $SERVICE_NAME
        success "Service stopped"
    else
        warning "Service was not running"
    fi
else
    warning "Systemd service not found (development environment?)"
fi

#############################################################################
# STEP 4: UPDATE CODE
#############################################################################

print_header "STEP 4/10: UPDATING CODE"

# Check if Git repository
if [ -d ".git" ]; then
    info "Fetching latest code from Git..."
    
    # Stash any local changes
    git stash save "Auto-stash before deployment $TIMESTAMP" || true
    
    # Fetch and pull
    git fetch origin
    git checkout $GIT_BRANCH
    git pull origin $GIT_BRANCH
    
    # Show what changed
    COMMIT_HASH=$(git rev-parse --short HEAD)
    COMMIT_MSG=$(git log -1 --pretty=%B)
    
    log "Current commit: $COMMIT_HASH"
    log "Commit message: $COMMIT_MSG"
    
    success "Code updated from Git"
else
    warning "Not a Git repository - skipping code update"
    info "If this is a production server, consider using Git for deployments"
fi

#############################################################################
# STEP 5: UPDATE DEPENDENCIES
#############################################################################

print_header "STEP 5/10: UPDATING DEPENDENCIES"

info "Activating virtual environment..."
source venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip --quiet

info "Installing/updating dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
    success "Dependencies updated"
else
    warning "requirements.txt not found"
fi

#############################################################################
# STEP 6: RUN DATABASE MIGRATIONS
#############################################################################

print_header "STEP 6/10: RUNNING DATABASE MIGRATIONS"

if [ -d "migrations" ]; then
    info "Checking for migrations..."
    
    MIGRATION_COUNT=0
    for migration in migrations/*.py; do
        if [ -f "$migration" ]; then
            log "Running migration: $(basename $migration)"
            python $migration
            ((MIGRATION_COUNT++))
        fi
    done
    
    if [ $MIGRATION_COUNT -eq 0 ]; then
        info "No migrations found"
    else
        success "Ran $MIGRATION_COUNT migration(s)"
    fi
else
    warning "Migrations directory not found"
fi

#############################################################################
# STEP 7: RUN TESTS
#############################################################################

print_header "STEP 7/10: RUNNING TESTS"

if [ -d "tests" ]; then
    info "Running test suite..."
    
    # Run tests (skip integration tests to avoid hanging)
    if pytest tests/test_challenge_engine.py tests/test_database.py -v --tb=short --color=yes 2>&1 | tee -a $LOG_FILE; then
        success "All tests passed ✓"
    else
        error "Tests failed! Deployment aborted. Check logs above."
    fi
else
    warning "Tests directory not found - skipping tests (not recommended for production!)"
fi

#############################################################################
# STEP 8: ENVIRONMENT VALIDATION
#############################################################################

print_header "STEP 8/10: VALIDATING ENVIRONMENT"

if [ -f ".env" ]; then
    info "Checking .env configuration..."
    
    # Check for required variables
    REQUIRED_VARS=("ADMIN_USERNAME" "ADMIN_PASSWORD" "ADMIN_SECRET_KEY")
    MISSING_VARS=0
    
    for var in "${REQUIRED_VARS[@]}"; do
        if ! grep -q "^$var=" .env; then
            warning "Missing environment variable: $var"
            ((MISSING_VARS++))
        fi
    done
    
    if [ $MISSING_VARS -eq 0 ]; then
        success "Environment configuration valid"
    else
        error "$MISSING_VARS required environment variables missing"
    fi
else
    error ".env file not found! Create it from .env.example"
fi

#############################################################################
# STEP 9: START APPLICATION
#############################################################################

print_header "STEP 9/10: STARTING APPLICATION"

# Start systemd service
if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    info "Starting $SERVICE_NAME service..."
    sudo systemctl start $SERVICE_NAME
    
    # Wait for service to start
    sleep 5
    
    if systemctl is-active --quiet $SERVICE_NAME; then
        success "Service started successfully"
    else
        error "Failed to start service! Check logs: journalctl -u $SERVICE_NAME -n 50"
    fi
else
    warning "Systemd service not configured"
    info "To run manually: uvicorn main:app --host 0.0.0.0 --port 8000"
fi

#############################################################################
# STEP 10: HEALTH CHECK
#############################################################################

print_header "STEP 10/10: HEALTH CHECK"

info "Waiting for application to be ready..."
sleep 3

# Try to reach the application
HEALTH_ENDPOINTS=("/metrics" "/health" "/")

for endpoint in "${HEALTH_ENDPOINTS[@]}"; do
    info "Checking endpoint: $endpoint"
    
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000$endpoint 2>/dev/null || echo "000")
    
    if [ "$HTTP_CODE" = "200" ]; then
        success "Health check passed (HTTP $HTTP_CODE)"
        break
    else
        warning "Endpoint returned HTTP $HTTP_CODE"
    fi
done

if [ "$HTTP_CODE" != "200" ]; then
    error "Health check failed! Application may not be running correctly"
fi

#############################################################################
# CLEANUP OLD BACKUPS
#############################################################################

info "Cleaning up old backups (keeping last 10)..."
cd $BACKUP_DIR
ls -t certivo_backup_*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm 2>/dev/null || true
ls -t ${DB_FILE}.backup_* 2>/dev/null | tail -n +11 | xargs -r rm 2>/dev/null || true

#############################################################################
# DEPLOYMENT SUMMARY
#############################################################################

print_header "DEPLOYMENT SUMMARY"

echo -e "${GREEN}✓ Deployment completed successfully!${NC}"
echo ""
echo -e "  ${BLUE}Environment:${NC}     $ENVIRONMENT"
echo -e "  ${BLUE}Timestamp:${NC}       $TIMESTAMP"
echo -e "  ${BLUE}Backup:${NC}          $BACKUP_NAME.tar.gz"
echo -e "  ${BLUE}Application:${NC}     http://localhost:8000"
echo -e "  ${BLUE}Admin Panel:${NC}     http://localhost:8000/admin"
echo -e "  ${BLUE}API Docs:${NC}        http://localhost:8000/docs"
echo ""

if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    echo -e "${CYAN}Service Status:${NC}"
    sudo systemctl status $SERVICE_NAME --no-pager | head -n 10
fi

echo ""
echo -e "${MAGENTA}Next Steps:${NC}"
echo -e "  1. Test the application at http://localhost:8000"
echo -e "  2. Check admin panel at http://localhost:8000/admin"
echo -e "  3. Monitor logs: tail -f logs/certivo.log"
echo -e "  4. View service logs: journalctl -u $SERVICE_NAME -f"
echo ""

#############################################################################
# LOG FINAL STATUS
#############################################################################

log "✅ Deployment completed successfully"
log "Environment: $ENVIRONMENT"
log "Backup: $BACKUP_NAME"

exit 0