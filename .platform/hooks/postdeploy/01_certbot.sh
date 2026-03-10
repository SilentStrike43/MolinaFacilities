#!/usr/bin/env bash
# Obtain or renew a Let's Encrypt cert for the domain.
# Runs after every deploy; certbot skips renewal if cert is still valid.

DOMAIN="app.gridlineservice.com"
EMAIL="admin@gridlineservice.com"   # change to real admin email

# Install certbot if not present
if ! command -v certbot &>/dev/null; then
    dnf install -y python3-certbot-nginx 2>/dev/null \
        || pip3 install certbot certbot-nginx
fi

# Obtain/renew cert using webroot (nginx serves the ACME challenge on port 80)
certbot certonly --webroot \
    --webroot-path /var/app/current \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN" \
    || exit 0   # don't fail deploy if certbot can't reach Let's Encrypt

# Reload nginx so it picks up a newly issued or renewed cert
systemctl reload nginx || true
