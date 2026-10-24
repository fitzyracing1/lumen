#!/usr/bin/env bash
# One command to run the Lumen bug benchmark against Amália on another machine.
#
#   AMALIA_BASE_URL=http://<that-machine>:8000/v1 ./scripts/amalia_bench.sh
#
# Optional: AMALIA_API_KEY, AMALIA_MODEL (default "amalia").
# Extra arguments are passed through to lumen_bench, e.g.:
#   ./scripts/amalia_bench.sh --memory bench/amalia-memory.json --max-cycles 5
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AMALIA_BASE_URL:?set AMALIA_BASE_URL, e.g. http://192.168.1.50:8000/v1 (LAN) or http://localhost:8000/v1 (tunnel)}"

echo "checking Amália at ${AMALIA_BASE_URL} ..."
if ! python3 -m lumen_bench --model amalia --check-only; then
    cat >&2 <<'EOF'

Amália is not reachable. Checklist:
  * Is the server running on the other machine, bound to the LAN
    (e.g. --host 0.0.0.0 --port 8000), not just localhost?
  * Can this machine reach it?  curl "$AMALIA_BASE_URL/models"
  * Using a tunnel instead?     ssh -L 8000:localhost:8000 user@that-machine
    then AMALIA_BASE_URL=http://localhost:8000/v1
  * Does the server need a key? export AMALIA_API_KEY=...
EOF
    exit 2
fi

exec python3 -m lumen_bench --model amalia "$@"
