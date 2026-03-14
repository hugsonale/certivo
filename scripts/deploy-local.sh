#!/bin/bash

#############################################################################
# Certivo Local Deployment Script (Windows/Development)
# Usage: ./scripts/deploy-local.sh
#############################################################################

set -e

echo "🚀 Starting local deployment..."

# Navigate to project directory
cd "$(dirname "$0")/.."

echo "📂 Current directory: $(pwd)"

# Check required files
echo "✓ Checking required files..."
for file in main.py database.py challenge_engine.py; do
    if [ ! -f "$file" ]; then
        echo "❌ Missing file: $file"
        exit 1
    fi
done

# Activate virtual environment
echo "✓ Activating virtual environment..."
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "❌ Virtual environment not found!"
    exit 1
fi

# Install/update dependencies
echo "✓ Installing dependencies..."
pip install -r requirements.txt --quiet

# Run tests
echo "✓ Running tests..."
pytest tests/test_challenge_engine.py tests/test_database.py -v --tb=short

# Create backup
echo "✓ Creating backup..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p backups
if [ -f "certivo_v2.db" ]; then
    cp certivo_v2.db "backups/certivo_v2.db.backup_$TIMESTAMP"
fi

echo ""
echo "✅ Local deployment check complete!"
echo ""
echo "To start the server:"
echo "  uvicorn main:app --reload"
echo ""

exit 0