# Nginx Configuration Guide

Complete guide for managing Nginx reverse proxy for Certivo.

---

## Installation (One-Time Setup)

### 1. Install Nginx
```bash
sudo ./scripts/install-nginx.sh yourdomain.com
```

### 2. Setup SSL Certificate
```bash
sudo ./scripts/setup-ssl.sh yourdomain.com
```

### 3. Test Configuration
```bash
sudo nginx -t
```

### 4. Reload Nginx
```bash
sudo systemctl reload nginx
```

---

## Daily Operations

### Test Configuration
```bash
sudo nginx -t
# OR
./scripts/nginx.sh test
```

### Reload Nginx (after config changes)
```bash
sudo systemctl reload nginx
# OR
./scripts/nginx.sh reload
```

### Restart Nginx
```bash
sudo systemctl restart nginx
# OR
./scripts/nginx.sh restart
```

### Check Status
```bash
sudo systemctl status nginx
# OR
./scripts/nginx.sh status
```

### View Logs
```bash
# Error logs
sudo tail -f /var/log/nginx/certivo_error.log
# OR
./scripts/nginx.sh logs

# Access logs
sudo tail -f /var/log/nginx/certivo_access.log
# OR
./scripts/nginx.sh access
```

---

## Configuration Files

### Main Config
```
/etc/nginx/sites-available/certivo
```

### Proxy Parameters
```
/etc/nginx/proxy_params
```

### SSL Certificates
```
/etc/letsencrypt/live/yourdomain.com/fullchain.pem
/etc/letsencrypt/live/yourdomain.com/privkey.pem
```

---

## Updating Configuration

### 1. Edit Local Config
```bash
nano config/nginx-certivo.conf
```

### 2. Copy to Server
```bash
sudo cp config/nginx-certivo.conf /etc/nginx/sites-available/certivo
```

### 3. Test
```bash
sudo nginx -t
```

### 4. Reload
```bash
sudo systemctl reload nginx
```

---

## Rate Limits

| Endpoint | Limit | Burst |
|----------|-------|-------|
| `/v1/challenge` | 30/min | 5 |
| `/v1/verify` | 10/min | 2 |
| `/admin/*` | 50/min | 20 |
| `/*` (general) | 100/sec | 50 |

---

## SSL Certificate Renewal

Auto-renewal is configured via cron (runs daily at 3 AM).

Manual renewal:
```bash
sudo certbot renew
sudo systemctl reload nginx
```

---

## Troubleshooting

### Configuration Test Failed
```bash
# Check syntax
sudo nginx -t

# View specific errors
sudo tail -n 50 /var/log/nginx/error.log
```

### Port 80/443 Already in Use
```bash
# Check what's using ports
sudo lsof -i :80
sudo lsof -i :443

# Stop conflicting service
sudo systemctl stop apache2  # If Apache is running
```

### SSL Certificate Issues
```bash
# Check certificate
sudo certbot certificates

# Renew certificate
sudo certbot renew --force-renewal

# Fix permissions
sudo chmod 644 /etc/letsencrypt/live/yourdomain.com/*.pem
```

### 502 Bad Gateway
```bash
# Check if application is running
sudo systemctl status certivo

# Check if backend is accessible
curl http://127.0.0.1:8000/health

# Check nginx error logs
sudo tail -f /var/log/nginx/certivo_error.log
```

---

## Security Headers Test
```bash
curl -I https://yourdomain.com
```

Should see headers:
- `Strict-Transport-Security`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Content-Security-Policy`

---

## Performance Testing
```bash
# Test SSL configuration
openssl s_client -connect yourdomain.com:443

# Check SSL rating
# Visit: https://www.ssllabs.com/ssltest/

# Load testing
ab -n 1000 -c 10 https://yourdomain.com/
```

---

## Useful Commands
```bash
# Show nginx version
nginx -v

# Show compiled modules
nginx -V

# Check all sites
ls -la /etc/nginx/sites-enabled/

# View main config
cat /etc/nginx/nginx.conf

# Check listening ports
sudo netstat -tulpn | grep nginx
```