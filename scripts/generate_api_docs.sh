#!/bin/bash
# Generate API documentation from OpenAPI spec

set -e

echo "🔄 Generating API documentation..."

# Install redoc-cli if not present
if ! command -v redoc-cli &> /dev/null; then
    echo "📦 Installing redoc-cli..."
    npm install -g redoc-cli
fi

# Generate HTML documentation
redoc-cli bundle api/openapi.yaml \
    --output docs/api-reference.html \
    --title "Certivo API Reference"

echo "✅ API documentation generated: docs/api-reference.html"

# Generate Markdown documentation (optional)
if command -v widdershins &> /dev/null; then
    widdershins api/openapi.yaml \
        --output docs/api-reference.md \
        --summary
    echo "✅ Markdown documentation generated: docs/api-reference.md"
fi