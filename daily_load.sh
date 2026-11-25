#!/usr/bin/env bash
# Daily refresh: wipe the seed tables and reload scenarios.txt with dates rebased to today.
#   ./daily_load.sh              # as of today
#   ./daily_load.sh 2026-12-01   # as of a given date
# Nothing is loaded unless the rebased data passes validate_scenarios.py.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"   # cron runs with a minimal PATH

cd "$(dirname "$0")"
AS_OF="${1:-$(date +%F)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 -I generate_dml.py scenarios.txt "$TMP/02-data.sql" --as-of "$AS_OF" --dump-json "$TMP/scenarios.json"
python3 -I validate_scenarios.py "$TMP/scenarios.json"
docker exec -i funder-postgres psql -U funder_admin -d auto_funding_db -v ON_ERROR_STOP=1 -q < "$TMP/02-data.sql"
cp "$TMP/02-data.sql" init/02-data.sql   # keep the last loaded SQL for fresh containers
echo "Loaded seed data as of $AS_OF"
