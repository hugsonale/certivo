#!/bin/bash

#############################################################################
# Install and Configure Nginx for Certivo
# Usage: sudo ./scripts/install-nginx.sh yourdomain.com
#############################################################################

DOMAIN=${1:-yourdomain.com}

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root: sudo ./scripts/install-nginx.sh"
    exit 1
fi

echo "🌐 Installing and configuring Nginx for Certivo..."

#############################################################################
# Install Nginx
#############################################################################

echo "📦 Installing Nginx..."

# Ubuntu/Debian
if command -v apt &> /dev/null; then
    apt update
    apt install -y nginx
fi

# CentOS/RHEL
if command -v yum &> /dev/null; then
    yum install -y nginx
fi

#############################################################################
# Create Directories
#############################################################################

echo "📁 Creating directories..."

mkdir -p /var/www/certbot
mkdir -p /opt/certivo/static/errors
mkdir -p /var/log/nginx

#############################################################################
# Install Proxy Params
#############################################################################

echo "⚙️  Installing proxy parameters..."

if [ ! -f "/etc/nginx/proxy_params" ]; then
    cp config/nginx-proxy-params.conf /etc/nginx/proxy_params
    echo "✓ Proxy params installed"
else
    echo "✓ Proxy params already exist"
fi

#############################################################################
# Install Site Configuration
#############################################################################

echo "⚙️  Installing site configuration..."

# Replace domain in config
sed "s/yourdomain.com/$DOMAIN/g" config/nginx-certivo.conf > /tmp/certivo-nginx.conf

# Copy to sites-available
cp /tmp/certivo-nginx.conf /etc/nginx/sites-available/certivo

# Enable site
ln -sf /etc/nginx/sites-available/certivo /etc/nginx/sites-enabled/certivo

# Remove default site
rm -f /etc/nginx/sites-enabled/default

echo "✓ Site configuration installed"

#############################################################################
# Create 429 Error Page
#############################################################################

echo "📄 Creating error pages..."

cat > /opt/certivo/static/errors/429.html <<'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>Too Many Requests</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }
        .error-box {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 500px;
            margin: 0 auto;
        }
        h1 { color: #e74c3c; }
        p { color: #666; }
    </style>
</head>
<body>
    <div class="error-box">
        <h1>429 - Too Many Requests</h1>
        <p>You've exceeded the rate limit. Please wait a moment and try again.</p>
        <p><small>This is a security measure to protect against automated attacks.</small></p>
    </div>
</body>
</html>
EOF

#############################################################################
# Test Configuration
#############################################################################

echo "🧪 Testing Nginx configuration..."

nginx -t

if [ $? -eq 0 ]; then
    echo "✓ Configuration is valid"
else
    echo "❌ Configuration has errors!"
    exit 1
fi

#############################################################################
# Enable and Start Nginx
#############################################################################

echo "▶️  Starting Nginx..."

systemctl enable nginx
systemctl restart nginx

#############################################################################
# Firewall Configuration
#############################################################################

echo "🔥 Configuring firewall..."

if command -v ufw &> /dev/null; then
    ufw allow 'Nginx Full'
    ufw allow 'Nginx HTTP'
    ufw allow 'Nginx HTTPS'
    echo "✓ UFW rules added"
fi

if command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
    echo "✓ Firewalld rules added"
fi

#############################################################################
# Summary
#############################################################################

echo ""
echo "✅ Nginx installation complete!"
echo ""
echo "Configuration file: /etc/nginx/sites-available/certivo"
echo "Domain: $DOMAIN"
echo ""
echo "Next steps:"
echo "  1. Setup SSL: sudo ./scripts/setup-ssl.sh $DOMAIN"
echo "  2. Update domain in config if needed"
echo "  3. Reload nginx: sudo systemctl reload nginx"
echo ""
echo "Check status:"
echo "  sudo systemctl status nginx"
echo "  sudo nginx -t"
echo ""

exit 0