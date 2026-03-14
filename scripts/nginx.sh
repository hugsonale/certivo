#!/bin/bash

#############################################################################
# Nginx Management Helper
# Usage: ./scripts/nginx.sh [test|reload|restart|status|logs]
#############################################################################

ACTION=$1

if [ -z "$ACTION" ]; then
    echo "Usage: ./scripts/nginx.sh [test|reload|restart|status|logs|access|error]"
    exit 1
fi

case "$ACTION" in
    test)
        echo "🧪 Testing Nginx configuration..."
        sudo nginx -t
        ;;
    
    reload)
        echo "🔄 Reloading Nginx..."
        sudo nginx -t && sudo systemctl reload nginx
        ;;
    
    restart)
        echo "🔄 Restarting Nginx..."
        sudo systemctl restart nginx
        sleep 1
        sudo systemctl status nginx --no-pager
        ;;
    
    status)
        echo "📊 Nginx status:"
        sudo systemctl status nginx --no-pager
        ;;
    
    logs)
        echo "📋 Nginx error logs (press Ctrl+C to exit):"
        sudo tail -f /var/log/nginx/certivo_error.log
        ;;
    
    access)
        echo "📋 Nginx access logs (press Ctrl+C to exit):"
        sudo tail -f /var/log/nginx/certivo_access.log
        ;;
    
    error)
        echo "📋 Recent Nginx errors:"
        sudo tail -n 50 /var/log/nginx/certivo_error.log
        ;;
    
    *)
        echo "❌ Unknown action: $ACTION"
        echo "Valid actions: test, reload, restart, status, logs, access, error"
        exit 1
        ;;
esac

exit 0