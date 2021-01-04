#!/bin/sh
set -e
ME=$(basename "$0")
DEFAULT_CONF_FILE="/etc/nginx/conf.d/simplelogin.conf"
if [ -f $DEFAULT_CONF_FILE ]; then
    echo "$ME: info: Simplelogin Nginx configuration file is already exists."
    exit 0
fi
echo "$ME: info: No configuration found. Going to create one."
cat <<EOT > $DEFAULT_CONF_FILE
server {
    listen       80;
    listen  [::]:80;
    server_name  sl.doanguyen.com;

    location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_pass   http://webapp:7777;
    }

    error_page  404 /404.html;
    # redirect server error pages to the static page /50x.html
    error_page   500 502 503 504  /50x.html;
    location = /50x.html {
        root   /usr/share/nginx/html;
    }
}
EOT