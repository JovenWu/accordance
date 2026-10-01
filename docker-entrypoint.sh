#!/bin/sh
set -e

# Drop privileges before running the app. We start as root only to fix the
# ownership of the bind-mounted data dir — its UID is inherited from the host,
# so it can't be chowned at build time — then exec the workload as the
# unprivileged `app` user via gosu. This way a parsing-library RCE (libgl /
# onnxruntime / pymupdf on untrusted PDFs) never lands as root.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data/pdfs
  chown -R app:app /app/data
  exec gosu app "$@"
fi

exec "$@"
