# Certivo Deployment Guide

Complete guide for deploying Certivo to production.

---

## 📋 Table of Contents

1. [Server Requirements](#server-requirements)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Installation Steps](#installation-steps)
4. [Configuration](#configuration)
5. [HTTPS Setup](#https-setup)
6. [Database Setup](#database-setup)
7. [Process Management](#process-management)
8. [Monitoring Setup](#monitoring-setup)
9. [Backup Procedures](#backup-procedures)
10. [Update Procedures](#update-procedures)
11. [Rollback Procedures](#rollback-procedures)
12. [Troubleshooting](#troubleshooting)

---

## 💻 Server Requirements

### Minimum Specifications
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 20GB SSD
- **OS:** Ubuntu 20.04+ or Windows Server 2019+
- **Python:** 3.9+
- **Network:** 100 Mbps

### Recommended Specifications
- **CPU:** 4+ cores
- **RAM:** 8GB+
- **Storage:** 50GB+ SSD
- **OS:** Ubuntu 22.04 LTS
- **Python:** 3.11+
- **Network:** 1 Gbps

### Expected Capacity
- **Users:** 1,000+ verifications/hour
- **Concurrent:** 50+ simultaneous users
- **Storage Growth:** ~100MB/day (logs + database)

---

## ✅ Pre-Deployment Checklist

### Code Preparation
- [ ] All tests passing (`pytest tests/`)
- [ ] Code coverage > 60%
- [ ] No hardcoded secrets
- [ ] Environment variables configured
- [ ] Database migrations ready

### Security
- [ ] Strong admin password set
- [ ] Secret keys generated (64+ characters)
- [ ] CORS origins configured
- [ ] Rate limiting enabled
- [ ] HTTPS certificates ready

### Infrastructure
- [ ] Domain name configured
- [ ] DNS records set
- [ ] Firewall rules configured
- [ ] SSL/TLS certificates obtained
- [ ] Backup system ready

---

## 🚀 Installation Steps

### Step 1: Server Setup (Ubuntu)
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Install system dependencies
sudo apt install build-essential libssl-dev libffi-dev python3-dev -y
sudo apt install ffmpeg libsm6 libxext6 -y  # For OpenCV

# Create application user
sudo useradd -m -s /bin/bash certivo
sudo usermod -aG sudo certivo
```

### Step 2: Application Setup
```bash
# Switch to certivo user
sudo su - certivo

# Clone repository (or upload files)
cd /opt
sudo mkdir certivo
sudo chown certivo:certivo certivo
cd certivo

# Upload your application files here

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Create requirements.txt

**Create `requirements.txt` in project root:**
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6
opencv-python==4.8.1.78
mediapipe==0.10.8
numpy==1.26.2
sqlalchemy==2.0.23
python-dotenv==1.0.0
bcrypt==4.1.2
psutil==5.9.6
jinja2==3.1.2
aiofiles==23.2.1
prometheus-client==0.19.0
locust==2.20.0
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
httpx==0.25.2
```

**Install:**
```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

### Step 1: Create .env File
```bash
# Navigate to application directory
cd /opt/certivo

# Create .env file
nano .env
```

**Add configuration:**
```bash
# Admin Authentication
ADMIN_USERNAME=admin
ADMIN_PASSWORD=CHANGE_THIS_STRONG_PASSWORD_NOW
ADMIN_SECRET_KEY=GENERATE_64_CHARACTER_RANDOM_STRING_HERE

# Database
DATABASE_URL=sqlite:///certivo_v2.db

# Security
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
MAX_UPLOAD_SIZE=10485760
RATE_LIMIT_ENABLED=true

# Environment
ENVIRONMENT=production

# Monitoring (Optional)
SENTRY_DSN=
ENABLE_METRICS=true
LOG_LEVEL=INFO
```

**Generate secret key:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 2: Set Permissions
```bash
chmod 600 .env
chown certivo:certivo .env
```

---

## 🔒 HTTPS Setup

### Option 1: Let's Encrypt (Free, Recommended)
```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Install Nginx
sudo apt install nginx -y

# Obtain certificate
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal
sudo certbot renew --dry-run
```

### Option 2: Custom Certificate
```bash
# Place certificates
sudo mkdir -p /etc/ssl/certivo
sudo cp your-cert.crt /etc/ssl/certivo/
sudo cp your-key.key /etc/ssl/certivo/

# Set permissions
sudo chmod 644 /etc/ssl/certivo/your-cert.crt
sudo chmod 600 /etc/ssl/certivo/your-key.key
```

### Nginx Configuration

**Create `/etc/nginx/sites-available/certivo`:**
```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

**Enable site:**
```bash
sudo ln -s /etc/nginx/sites-available/certivo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🗄️ Database Setup

### SQLite (Default - Small/Medium Scale)
```bash
# Database is created automatically on first run
# Located at: /opt/certivo/certivo_v2.db

# Run migrations
python migrations/add_trust_revocation.py
```

### PostgreSQL (Recommended for Production)

**Install PostgreSQL:**
```bash
sudo apt install postgresql postgresql-contrib -y
```

**Create database:**
```bash
sudo -u postgres psql

CREATE DATABASE certivo;
CREATE USER certivouser WITH PASSWORD 'strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE certivo TO certivouser;
\q
```

**Update .env:**
```bash
DATABASE_URL=postgresql://certivouser:strong_password_here@localhost/certivo
```

**Install PostgreSQL adapter:**
```bash
pip install psycopg2-binary
```

---

## 🔄 Process Management

### Option 1: Systemd (Recommended)

**Create `/etc/systemd/system/certivo.service`:**
```ini
[Unit]
Description=Certivo Human Verification System
After=network.target

[Service]
Type=notify
User=certivo
Group=certivo
WorkingDirectory=/opt/certivo
Environment="PATH=/opt/certivo/venv/bin"
ExecStart=/opt/certivo/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable certivo
sudo systemctl start certivo
sudo systemctl status certivo
```

**Check logs:**
```bash
sudo journalctl -u certivo -f
```

### Option 2: Supervisor

**Install:**
```bash
sudo apt install supervisor -y
```

**Create `/etc/supervisor/conf.d/certivo.conf`:**
```ini
[program:certivo]
directory=/opt/certivo
command=/opt/certivo/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
user=certivo
autostart=true
autorestart=true
stderr_logfile=/var/log/certivo/err.log
stdout_logfile=/var/log/certivo/out.log
```

**Start:**
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start certivo
```

---

## 📊 Monitoring Setup

### Prometheus + Grafana (Optional)

**Install Prometheus:**
```bash
sudo apt install prometheus -y
```

**Configure scraping (`/etc/prometheus/prometheus.yml`):**
```yaml
scrape_configs:
  - job_name: 'certivo'
    static_configs:
      - targets: ['localhost:8000']
```

**Install Grafana:**
```bash
sudo apt install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt update
sudo apt install grafana -y
sudo systemctl enable grafana-server
sudo systemctl start grafana-server
```

**Access Grafana:** `http://your-server:3000`

---

## 💾 Backup Procedures

### Daily Backup Script

**Create `/opt/certivo/backup.sh`:**
```bash
#!/bin/bash

# Configuration
BACKUP_DIR="/opt/certivo/backups"
DB_PATH="/opt/certivo/certivo_v2.db"
RETENTION_DAYS=30

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup filename with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/certivo_backup_$TIMESTAMP.db"

# Copy database
cp $DB_PATH $BACKUP_FILE

# Compress
gzip $BACKUP_FILE

# Delete old backups
find $BACKUP_DIR -name "certivo_backup_*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $BACKUP_FILE.gz"
```

**Make executable:**
```bash
chmod +x /opt/certivo/backup.sh
```

**Add to crontab:**
```bash
crontab -e

# Add this line (runs daily at 2 AM)
0 2 * * * /opt/certivo/backup.sh >> /var/log/certivo_backup.log 2>&1
```

---

## 🔄 Update Procedures

### Standard Update
```bash
# 1. Backup current version
sudo cp -r /opt/certivo /opt/certivo_backup_$(date +%Y%m%d)

# 2. Backup database
sudo cp /opt/certivo/certivo_v2.db /opt/certivo/certivo_v2.db.backup

# 3. Stop service
sudo systemctl stop certivo

# 4. Pull new code or upload files
cd /opt/certivo
# (upload new files here)

# 5. Install new dependencies
source venv/bin/activate
pip install -r requirements.txt

# 6. Run migrations if any
python migrations/add_trust_revocation.py

# 7. Test locally
uvicorn main:app --host 127.0.0.1 --port 8001
# Visit http://localhost:8001 to verify

# 8. Start service
sudo systemctl start certivo

# 9. Verify
sudo systemctl status certivo
curl https://yourdomain.com/metrics
```

---

## ⏮️ Rollback Procedures

### Quick Rollback
```bash
# 1. Stop current version
sudo systemctl stop certivo

# 2. Restore backup
sudo rm -rf /opt/certivo
sudo mv /opt/certivo_backup_20260312 /opt/certivo

# 3. Restore database
sudo cp /opt/certivo/certivo_v2.db.backup /opt/certivo/certivo_v2.db

# 4. Start service
sudo systemctl start certivo

# 5. Verify
sudo systemctl status certivo
```

---

## 🐛 Troubleshooting

### Service Won't Start
```bash
# Check service status
sudo systemctl status certivo

# Check logs
sudo journalctl -u certivo -n 100

# Check application logs
tail -f /opt/certivo/logs/errors.log

# Common fixes:
# - Check .env file exists and has correct values
# - Verify permissions (certivo user can read all files)
# - Check port 8000 is not in use
# - Verify Python virtual environment is activated
```

### Database Connection Errors
```bash
# Check database file exists
ls -la /opt/certivo/certivo_v2.db

# Check permissions
sudo chown certivo:certivo /opt/certivo/certivo_v2.db

# Test database
python3 -c "from database import engine; print(engine.table_names())"
```

### High Memory Usage
```bash
# Check memory
free -h

# Restart service
sudo systemctl restart certivo

# Reduce workers in systemd service
# Edit: /etc/systemd/system/certivo.service
# Change: --workers 4 to --workers 2
```

---

## 📞 Post-Deployment Checklist

- [ ] HTTPS working correctly
- [ ] Admin login functional
- [ ] Verification flow works end-to-end
- [ ] Metrics endpoint accessible (`/metrics`)
- [ ] Logs being written to `/opt/certivo/logs/`
- [ ] Backup cron job scheduled
- [ ] Monitoring configured
- [ ] Firewall rules in place
- [ ] Domain DNS configured
- [ ] Load testing completed

---

## 🔐 Security Hardening
```bash
# Firewall (UFW)
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable

# Fail2ban (protect against brute force)
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Automatic security updates
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

---

**Deployment Guide Version:** 1.0.0  
**Last Updated:** 2026-03-12