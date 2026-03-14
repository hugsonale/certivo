#!/bin/bash

#############################################################################
# Install Certivo Systemd Service
# Run with sudo: sudo ./scripts/install-service.sh
#############################################################################

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root: sudo ./scripts/install-service.sh"
    exit 1
fi

echo "⚙️  Installing Certivo systemd service..."

# Copy service file
echo "📋 Copying service file..."
cp config/certivo.service /etc/systemd/system/certivo.service

# Set correct permissions
chmod 644 /etc/systemd/system/certivo.service

# Reload systemd
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

# Enable service (start on boot)
echo "✅ Enabling service..."
systemctl enable certivo

echo ""
echo "✅ Service installed successfully!"
echo ""
echo "Commands you can use:"
echo "  sudo systemctl start certivo      # Start the service"
echo "  sudo systemctl stop certivo       # Stop the service"
echo "  sudo systemctl restart certivo    # Restart the service"
echo "  sudo systemctl status certivo     # Check status"
echo "  sudo journalctl -u certivo -f     # View live logs"
echo ""
echo "To start the service now:"
echo "  sudo systemctl start certivo"
echo ""

exit 0