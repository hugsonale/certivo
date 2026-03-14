#!/bin/bash

#############################################################################
# Setup SSL Certificate with Let's Encrypt
# Usage: sudo ./scripts/setup-ssl.sh yourdomain.com
#############################################################################

DOMAIN=$1

if [ -z "$DOMAIN" ]; then
    echo "❌ Error: Domain required"
    echo "Usage: sudo ./scripts/setup-ssl.sh yourdomain.com"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root: sudo ./scripts/setup-ssl.sh $DOMAIN"
    exit 1
fi

echo "🔒 Setting up SSL certificate for $DOMAIN"

#############################################################################
# Install Certbot
#############################################################################

echo "📦 Installing Certbot..."

# Ubuntu/Debian
if command -v apt &> /dev/null; then
    apt update
    apt install -y certbot python3-certbot-nginx
fi

# CentOS/RHEL
if command -v yum &> /dev/null; then
    yum install -y certbot python3-certbot-nginx
fi

#############################################################################
# Obtain Certificate
#############################################################################

echo "🎫 Obtaining SSL certificate..."

# Stop nginx temporarily
systemctl stop nginx

# Obtain certificate (standalone mode)
certbot certonly --standalone \
    -d $DOMAIN \
    -d www.$DOMAIN \
    --non-interactive \
    --agree-tos \
    --email admin@$DOMAIN \
    --preferred-challenges http

# Start nginx
systemctl start nginx

#############################################################################
# Setup Auto-Renewal
#############################################################################

echo "🔄 Setting up auto-renewal..."

# Test renewal
certbot renew --dry-run

# Add cron job for auto-renewal (if not exists)
CRON_CMD="0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'"

if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "✓ Auto-renewal cron job added"
else
    echo "✓ Auto-renewal cron job already exists"
fi

#############################################################################
# Verify
#############################################################################

echo ""
echo "✅ SSL certificate installed!"
echo ""
echo "Certificate locations:"
echo "  Certificate: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "  Private Key: /etc/letsencrypt/live/$DOMAIN/privkey.pem"
echo "  Chain: /etc/letsencrypt/live/$DOMAIN/chain.pem"
echo ""
echo "Auto-renewal is configured (runs daily at 3 AM)"
echo ""
echo "Next steps:"
echo "  1. Update nginx config with your domain"
echo "  2. sudo nginx -t"
echo "  3. sudo systemctl reload nginx"
echo ""

exit 0