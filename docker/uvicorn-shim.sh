#!/bin/sh
# Installed over the `uvicorn` command in the image. Railway can run a saved start command such as
# `uvicorn app.main:app --host 0.0.0.0 --port $PORT` with no shell, so uvicorn receives the text "$PORT".
# Replace that text with the real port, then hand over to the real uvicorn.
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  a="$1"; shift
  case "$a" in
    '$PORT'|'${PORT}') a="${PORT:-8000}" ;;
    '${PORT:-8000}') a="${PORT:-8000}" ;;
  esac
  set -- "$@" "$a"
  i=$((i + 1))
done
exec python -m uvicorn "$@"
