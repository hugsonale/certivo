#!/bin/bash

#############################################################################
# Certivo Service Management Helper
# Usage: ./scripts/service.sh [start|stop|restart|status|logs|enable|disable]
#############################################################################

ACTION=$1

if [ -z "$ACTION" ]; then
    echo "Usage: ./scripts/service.sh [start|stop|restart|status|logs|enable|disable]"
    exit 1
fi

case "$ACTION" in
    start)
        echo "▶️  Starting Certivo service..."
        sudo systemctl start certivo
        sleep 2
        sudo systemctl status certivo --no-pager
        ;;
    
    stop)
        echo "⏸️  Stopping Certivo service..."
        sudo systemctl stop certivo
        sleep 1
        sudo systemctl status certivo --no-pager
        ;;
    
    restart)
        echo "🔄 Restarting Certivo service..."
        sudo systemctl restart certivo
        sleep 2
        sudo systemctl status certivo --no-pager
        ;;
    
    status)
        echo "📊 Certivo service status:"
        sudo systemctl status certivo --no-pager
        ;;
    
    logs)
        echo "📋 Certivo service logs (press Ctrl+C to exit):"
        sudo journalctl -u certivo -f --no-pager
        ;;
    
    enable)
        echo "✅ Enabling Certivo service (start on boot)..."
        sudo systemctl enable certivo
        ;;
    
    disable)
        echo "❌ Disabling Certivo service (don't start on boot)..."
        sudo systemctl disable certivo
        ;;
    
    *)
        echo "❌ Unknown action: $ACTION"
        echo "Valid actions: start, stop, restart, status, logs, enable, disable"
        exit 1
        ;;
esac

exit 0