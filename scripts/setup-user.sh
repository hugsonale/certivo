#!/bin/bash

#############################################################################
# Create Certivo System User
# Run this script on production server to create dedicated user
#############################################################################

echo "🔐 Creating certivo system user..."

# Create user if doesn't exist
if id "certivo" &>/dev/null; then
    echo "✓ User 'certivo' already exists"
else
    # Create system user with home directory
    sudo useradd -r -m -s /bin/bash -d /opt/certivo certivo
    echo "✓ User 'certivo' created"
fi

# Create application directories
echo "📂 Creating application directories..."
sudo mkdir -p /opt/certivo/{logs,backups}

# Set ownership
echo "👤 Setting ownership..."
sudo chown -R certivo:certivo /opt/certivo

# Set permissions
echo "🔒 Setting permissions..."
sudo chmod 750 /opt/certivo
sudo chmod 770 /opt/certivo/logs
sudo chmod 770 /opt/certivo/backups

echo ""
echo "✅ Setup complete!"
echo ""
echo "User details:"
id certivo

exit 0