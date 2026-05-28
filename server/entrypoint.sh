#!/bin/sh
# Generate self-signed SSL certificates if they don't exist

SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/cert.pem"
KEY_FILE="$SSL_DIR/key.pem"
EMBED_CSP_FILE="/etc/nginx/conf.d/embed_frame_ancestors.conf"

# Create SSL directory if it doesn't exist
mkdir -p $SSL_DIR

# Generate self-signed certificate if it doesn't exist
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "Generating self-signed SSL certificate..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout $KEY_FILE \
        -out $CERT_FILE \
        -subj "/C=US/ST=State/L=City/O=AFT/CN=localhost" \
        2>/dev/null
    
    echo "SSL certificate generated successfully"
else
    echo "SSL certificate already exists"
fi

# Build embed frame-ancestor allowlist for public-board.html.
# Default is self-only embedding unless explicit trusted origins are provided.
embed_ancestors="'self'"

if [ -n "$EMBED_ALLOWED_ORIGINS" ]; then
    OLD_IFS="$IFS"
    IFS=','
    for raw_origin in $EMBED_ALLOWED_ORIGINS; do
        origin=$(printf '%s' "$raw_origin" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

        if [ -z "$origin" ]; then
            continue
        fi

        if printf '%s' "$origin" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?$'; then
            embed_ancestors="$embed_ancestors $origin"
        else
            echo "Ignoring invalid EMBED_ALLOWED_ORIGINS entry: $origin"
        fi
    done
    IFS="$OLD_IFS"
fi

cat > "$EMBED_CSP_FILE" <<EOF
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' wss:; frame-ancestors $embed_ancestors" always;
EOF

echo "Configured public-board frame-ancestors: $embed_ancestors"

# Start nginx
exec nginx -g 'daemon off;'
