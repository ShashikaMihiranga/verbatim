#!/bin/sh
# Railway can hand us a start command such as `uvicorn ... --port $PORT` without a shell, so $PORT stays
# literal. Run whatever command we are given through a shell so variables expand.
export PORT="${PORT:-8000}"
if [ "$#" -eq 0 ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi
if [ "$1" = "sh" ] && [ "$2" = "-c" ]; then
  exec "$@"
fi
exec sh -c "$*"
