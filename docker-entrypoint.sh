#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data/pdfs
  chown -R app:app /app/data
  exec gosu app "$@"
fi

exec "$@"
