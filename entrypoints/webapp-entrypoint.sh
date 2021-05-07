#!/bin/sh
echo "Starting the web app"
flask db upgrade
gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15
