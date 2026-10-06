# Certivo Installation Guide

Complete installation guide for local development and production deployment.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Production Installation](#production-installation)
4. [Database Setup](#database-setup)
5. [Configuration](#configuration)
6. [Running the Application](#running-the-application)
7. [Verification](#verification)
8. [Troubleshooting](#troubleshooting)

---

## 🔧 Prerequisites

### Required Software

- **Python:** 3.9+ (3.11 recommended)
- **Git:** Latest version
- **pip:** Latest version
- **Webcam:** For testing verification (development only)

### System Requirements

**Minimum (Development):**
- 2GB RAM
- 2 CPU cores
- 5GB disk space

**Recommended (Production):**
- 4GB+ RAM
- 4+ CPU cores
- 20GB+ SSD storage
- Ubuntu 22.04 LTS

---

## 💻 Local Development Setup

### 1. Clone Repository
```bash
git clone https://github.com/your-username/certivo.git
cd certivo
```

### 2. Create Virtual Environment

**Linux/Mac:**
```bash
python3.11 -m venv venv
source venv/bin/activate
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
# Upgrade pip
pip install --upgrade pip

# Install production dependencies
pip install -r requirements.txt

# Or install with development tools
pip install -r requirements-dev.txt
```

### 4. Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env  # Linux/Mac
notepad .env  # Windows
```

**Minimum configuration:**
```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password_here
ADMIN_SECRET_KEY=your_64_char_random_string
DATABASE_URL=sqlite:///certivo_v2.db
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

**Generate secret key:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Initialize Database
```bash
# Run migrations
python migrations/add_trust_revocation.py
```

### 6. Create Required Directories
```bash
mkdir -p logs backups
```

### 7. Run Development Server
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 8. Access Application

- **Frontend:** http://127.0.0.1:8000
- **API Docs:** http://127.0.0.1:8000/docs
- **Admin Panel:** http://127.0.0.1:8000/admin/login
- **Health Check:** http://127.0.0.1:8000/health
- **Metrics:** http://127.0.0.1:8000/metrics

---

## 🚀 Production Installation

### 1. Server Preparation
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Install system dependencies
sudo apt install build-essential libssl-dev libffi-dev python3-dev -y
sudo apt install ffmpeg libsm6 libxext6 -y  # For OpenCV
sudo apt install nginx certbot python3-certbot-nginx -y

# Install PostgreSQL (optional but recommended)
sudo apt install postgresql postgresql-contrib -y
```

### 2. Create Application User
```bash
# Run setup script
sudo ./scripts/setup-user.sh

# Or manually:
sudo useradd -r -m -s /bin/bash -d /opt/certivo certivo
sudo mkdir -p /opt/certivo/{logs,backups}
sudo chown -R certivo:certivo /opt/certivo
```

### 3. Deploy Application Files
```bash
# Upload files to server
scp -r * user@your-server:/opt/certivo/

# Or use git
cd /opt/certivo
git clone https://github.com/your-username/certivo.git .
```

### 4. Setup Virtual Environment
```bash
cd /opt/certivo
sudo -u certivo python3.11 -m venv venv
sudo -u certivo venv/bin/pip install --upgrade pip
sudo -u certivo venv/bin/pip install -r requirements.txt
```

### 5. Configure Production Environment
```bash
sudo -u certivo cp .env.example .env
sudo -u certivo nano .env
```

**Production configuration:**
```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=very_strong_password_min_20_chars
ADMIN_SECRET_KEY=64_char_random_generated_string
DATABASE_URL=postgresql://certivouser:password@localhost/certivo
ENVIRONMENT=production
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
SENTRY_DSN=your_sentry_dsn_here
ENABLE_METRICS=true
LOG_LEVEL=INFO
```

### 6. Setup Database (PostgreSQL)
```bash
# Create database and user
sudo -u postgres psql <<EOF
CREATE DATABASE certivo;
CREATE USER certivouser WITH PASSWORD 'strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE certivo TO certivouser;
\q
EOF

# Run migrations
sudo -u certivo /opt/certivo/venv/bin/python migrations/add_trust_revocation.py
```

### 7. Install Systemd Service
```bash
sudo ./scripts/install-service.sh
```

### 8. Install Nginx
```bash
sudo ./scripts/install-nginx.sh yourdomain.com
```

### 9. Setup SSL Certificate
```bash
sudo ./scripts/setup-ssl.sh yourdomain.com
```

### 10. Start Services
```bash
# Start Certivo
sudo systemctl start certivo
sudo systemctl enable certivo

# Reload Nginx
sudo systemctl reload nginx

# Check status
sudo systemctl status certivo
sudo systemctl status nginx
```

### 11. Setup Automated Backups
```bash
# Add to crontab
sudo -u certivo crontab -e

# Add this line (runs daily at 2 AM):
0 2 * * * /opt/certivo/scripts/backup.sh >> /var/log/certivo_backup.log 2>&1
```

---

## 🗄️ Database Setup

### SQLite (Default - Development)
```bash
# Automatic - no setup needed
# Database file: certivo_v2.db
```

### PostgreSQL (Production)
```bash
# 1. Install PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# 2. Create database
sudo -u postgres createdb certivo

# 3. Create user
sudo -u postgres createuser certivouser --pwprompt

# 4. Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE certivo TO certivouser;"

# 5. Update .env
DATABASE_URL=postgresql://certivouser:password@localhost/certivo

# 6. Run migrations
python migrations/add_trust_revocation.py
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ADMIN_USERNAME` | Yes | - | Admin login username |
| `ADMIN_PASSWORD` | Yes | - | Admin login password |
| `ADMIN_SECRET_KEY` | Yes | - | Session secret (64 chars) |
| `DATABASE_URL` | Yes | sqlite:///certivo_v2.db | Database connection |
| `ENVIRONMENT` | No | production | Environment name |
| `ALLOWED_ORIGINS` | Yes | - | CORS allowed origins |
| `RATE_LIMIT_ENABLED` | No | true | Enable rate limiting |
| `SENTRY_DSN` | No | - | Sentry error tracking |
| `LOG_LEVEL` | No | INFO | Logging level |

### Security Checklist

- [ ] Strong admin password (20+ characters)
- [ ] Unique secret key (64+ characters)
- [ ] HTTPS enabled (production)
- [ ] CORS origins restricted
- [ ] Rate limiting enabled
- [ ] Firewall configured
- [ ] Regular backups scheduled

---

## ▶️ Running the Application

### Development
```bash
# With auto-reload
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# With specific workers
uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
```

### Production (Systemd)
```bash
# Start
sudo systemctl start certivo

# Stop
sudo systemctl stop certivo

# Restart
sudo systemctl restart certivo

# Status
sudo systemctl status certivo

# Logs
sudo journalctl -u certivo -f
```

### Production (Manual)
```bash
# As certivo user
sudo -u certivo /opt/certivo/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info
```

---

## ✅ Verification

### 1. Check Services
```bash
# Application
curl http://localhost:8000/health

# Expected: {"status": "healthy", ...}

# Nginx
curl -I https://yourdomain.com

# Expected: HTTP/2 200
```

### 2. Run Tests
```bash
# Unit tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=html

# Expected: All tests passing
```

### 3. Test Verification Flow

1. Visit http://localhost:8000 or https://yourdomain.com
2. Click "Start Verification"
3. Allow camera access
4. Complete face calibration
5. Complete challenge
6. Check result

### 4. Test Admin Panel

1. Visit http://localhost:8000/admin/login
2. Login with credentials from .env
3. Check dashboard loads
4. Verify metrics display

### 5. Check Metrics
```bash
curl http://localhost:8000/metrics

# Should see Prometheus metrics
```

---

## 🐛 Troubleshooting

### Import Error: No module named 'cv2'
```bash
pip install opencv-python
```

### Import Error: No module named 'mediapipe'
```bash
pip install mediapipe
```

### Database Connection Error
```bash
# SQLite
rm certivo_v2.db
python migrations/add_trust_revocation.py

# PostgreSQL
sudo systemctl status postgresql
sudo -u postgres psql -c "SELECT 1;"
```

### Port Already in Use
```bash
# Find process
sudo lsof -i :8000

# Kill process
sudo kill -9 <PID>

# Or use different port
uvicorn main:app --port 8001
```

### Permission Denied
```bash
# Fix ownership
sudo chown -R certivo:certivo /opt/certivo

# Fix permissions
sudo chmod -R 755 /opt/certivo
sudo chmod 770 /opt/certivo/logs
```

### Service Won't Start
```bash
# Check logs
sudo journalctl -u certivo -n 100

# Check config
sudo systemctl cat certivo

# Test manually
cd /opt/certivo
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Nginx 502 Bad Gateway
```bash
# Check if app is running
sudo systemctl status certivo

# Check nginx logs
sudo tail -f /var/log/nginx/certivo_error.log

# Test backend
curl http://127.0.0.1:8000/health
```

### SSL Certificate Issues
```bash
# Renew certificate
sudo certbot renew

# Test certificate
sudo certbot certificates

# Fix permissions
sudo chmod 644 /etc/letsencrypt/live/yourdomain.com/*.pem
```

---

## 📚 Next Steps

After installation:

1. **Read Documentation:**
   - [ARCHITECTURE.md](ARCHITECTURE.md) - System design
   - [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment guide
   - [ADMIN_GUIDE.md](ADMIN_GUIDE.md) - Admin dashboard
   - [API Documentation](http://localhost:8000/docs)

2. **Test Verification Flow:**
   - Try all 6 challenge types
   - Test on different browsers
   - Test on mobile devices

3. **Configure Monitoring:**
   - Setup Sentry error tracking
   - Configure Prometheus + Grafana
   - Setup uptime monitoring

4. **Setup Backups:**
   - Test backup script
   - Configure cloud backup (optional)
   - Document restore procedure

5. **Security Hardening:**
   - Review firewall rules
   - Setup fail2ban
   - Enable automatic updates

---

## 🆘 Getting Help

- **Documentation:** Check `/docs` folder
- **Logs:** Check `logs/` directory
- **Issues:** GitHub Issues
- **Security:** Email security@certivo.com

---

**Installation Guide Version:** 1.0.0  
**Last Updated:** 2026-03-12  
**Tested On:** Ubuntu 22.04 LTS, Python 3.11