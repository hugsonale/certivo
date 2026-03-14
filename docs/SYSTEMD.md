# Systemd Service Management Guide

Quick reference for managing the Certivo systemd service.

---

## Installation (One-Time Setup)

### 1. Create System User
```bash
sudo ./scripts/setup-user.sh
```

### 2. Install Service
```bash
sudo ./scripts/install-service.sh
```

### 3. Start Service
```bash
sudo systemctl start certivo
```

---

## Daily Operations

### Start Service
```bash
sudo systemctl start certivo
# OR
./scripts/service.sh start
```

### Stop Service
```bash
sudo systemctl stop certivo
# OR
./scripts/service.sh stop
```

### Restart Service
```bash
sudo systemctl restart certivo
# OR
./scripts/service.sh restart
```

### Check Status
```bash
sudo systemctl status certivo
# OR
./scripts/service.sh status
```

### View Logs (Live)
```bash
sudo journalctl -u certivo -f
# OR
./scripts/service.sh logs
```

### View Logs (Last 100 lines)
```bash
sudo journalctl -u certivo -n 100
```

### View Logs (Since Today)
```bash
sudo journalctl -u certivo --since today
```

### View Logs (Last Hour)
```bash
sudo journalctl -u certivo --since "1 hour ago"
```

---

## Enable/Disable Auto-Start

### Enable (Start on Boot)
```bash
sudo systemctl enable certivo
# OR
./scripts/service.sh enable
```

### Disable (Don't Start on Boot)
```bash
sudo systemctl disable certivo
# OR
./scripts/service.sh disable
```

### Check If Enabled
```bash
systemctl is-enabled certivo
```

---

## Troubleshooting

### Service Won't Start
```bash
# Check service status
sudo systemctl status certivo

# Check detailed logs
sudo journalctl -u certivo -n 100 --no-pager

# Check if .env file exists
ls -la /opt/certivo/.env

# Check if virtual environment exists
ls -la /opt/certivo/venv/bin/uvicorn

# Test running manually
cd /opt/certivo
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Service Keeps Restarting
```bash
# Check what's causing crashes
sudo journalctl -u certivo -n 200

# Check system resources
free -h
df -h
top
```

### Permission Errors
```bash
# Fix ownership
sudo chown -R certivo:certivo /opt/certivo

# Fix permissions
sudo chmod 750 /opt/certivo
sudo chmod 770 /opt/certivo/logs
```

### Port Already in Use
```bash
# Check what's using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>

# Or use different port in service file
```

---

## Configuration Changes

After editing `config/certivo.service`:
```bash
# 1. Copy updated file
sudo cp config/certivo.service /etc/systemd/system/

# 2. Reload systemd
sudo systemctl daemon-reload

# 3. Restart service
sudo systemctl restart certivo
```

---

## Uninstallation
```bash
# Stop service
sudo systemctl stop certivo

# Disable service
sudo systemctl disable certivo

# Remove service file
sudo rm /etc/systemd/system/certivo.service

# Reload systemd
sudo systemctl daemon-reload
```

---

## Service File Location
```
/etc/systemd/system/certivo.service
```

---

## Useful Commands
```bash
# Reload systemd after changes
sudo systemctl daemon-reload

# Show service file
systemctl cat certivo

# Show service dependencies
systemctl list-dependencies certivo

# Check if service is running
systemctl is-active certivo

# Check if service is enabled
systemctl is-enabled certivo

# Show service properties
systemctl show certivo
```