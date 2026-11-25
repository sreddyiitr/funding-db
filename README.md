# Auto Funding Test Database

A local Postgres 18 database seeded with 110 auto-loan funding applications for testing. The test data is reloaded with dates shifted to today, so deadlines, SLAs and expiry windows always look current.

## What's in here

| File | Purpose |
|---|---|
| `docker-compose.yml` | Postgres 18 container (`funder-postgres`) on port 5432 |
| `init/01-schema.sql` | Schema: enums, 10 tables, indexes, triggers |
| `init/02-data.sql` | Generated seed data (the last load). Do not edit by hand. |
| `scenarios.txt` | Source of truth: 110 scenarios as JSON |
| `scenarios.orig.txt` | Original, unfixed copy of the scenarios (for reference only) |
| `generate_dml.py` | Turns `scenarios.txt` into SQL, shifting dates to a chosen day |
| `validate_scenarios.py` | Checks a scenarios file against the PRD rules |
| `daily_load.sh` | Generate → validate → wipe and reload, in one step |

Tables: `actors`, `task_category_owners`, `dealers`, `applications`, `applicants`, `vehicles`, `loan_terms`, `funding_tasks`, `activity_events`, `risc_line_items`.

The rules for writing new scenarios are in the **Auto Funding Test Data PRD** (https://claude.ai/artifact/NfKSQHY5oMJgnSEi6hWDKF).

## Prerequisites

- **Docker Desktop** (or another Docker engine with Compose v2), running
- **Python 3.9+**. The scripts use only the standard library, so you don't need `pip install`.
- **Bash** (macOS and Linux have it; on Windows, use WSL or Git Bash)
- Port **5432** free on your machine. Stop any local Postgres first, or change the port mapping (see Troubleshooting).

Check them:

```bash
docker --version && docker compose version
python3 --version
```

## Quick start

```bash
# 1. Get the project and go into it
cd funding-db

# 2. Start Postgres. On first start, the scripts in init/ run automatically:
#    01-schema.sql creates the schema, 02-data.sql loads the data.
docker compose up -d

# 3. Wait until the container reports healthy
docker compose ps

# 4. Reload the data with dates shifted to today
./daily_load.sh
```

Step 4 matters on a new machine. The `init/02-data.sql` you received is dated the day it was last generated, and `daily_load.sh` shifts it to today.

If `./daily_load.sh` says "permission denied", run `chmod +x daily_load.sh` once.

## Connecting

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `auto_funding_db` |
| User | `funder_admin` |
| Password | `funder_dev_password` |

```bash
# psql inside the container (no local install needed)
docker exec -it funder-postgres psql -U funder_admin -d auto_funding_db

# Connection URL for apps and GUI clients (DBeaver, TablePlus, pgAdmin, etc.)
postgresql://funder_admin:funder_dev_password@localhost:5432/auto_funding_db
```

These are local development credentials. Don't reuse them anywhere real.

## Refreshing the data daily

`scenarios.txt` is a template. You never edit its dates. On each run, `daily_load.sh` does the following:

1. Shifts every timestamp forward or back by a whole number of days, so the file's `generatedAt` date becomes the load date. Times of day stay the same, including the 17:00 SLA cutoff.
2. Runs `validate_scenarios.py` on the shifted data. If any check fails, it stops and leaves the database alone.
3. Clears all 10 tables and reloads them in **one transaction**, so a failed load leaves yesterday's data in place.
4. Copies the loaded SQL to `init/02-data.sql`, so a fresh container starts with recent data.

```bash
./daily_load.sh               # load with dates shifted to today
./daily_load.sh 2026-12-15    # load with dates shifted to any other date
```

### Run it automatically (macOS and Linux, cron)

Run `crontab -e` and add the line below, replacing `/path/to/funding-db` with your project folder:

```cron
30 8 * * * /path/to/funding-db/daily_load.sh >> /path/to/funding-db/daily_load.log 2>&1
```

- Schedule it **after 08:10 US Central**. The newest events in the data are at 08:08 Central, and an earlier run would put them in the future.
- At the scheduled time, Docker must be running and the machine awake. A run missed while the machine was asleep doesn't catch up later. Run `./daily_load.sh` by hand in that case.
- On macOS, cron may need Full Disk Access to read a project inside `~/Documents`. Grant it in System Settings → Privacy & Security → Full Disk Access → add `/usr/sbin/cron`.

## Working with the scripts directly

```bash
# Check a scenarios file (exits with code 1 and lists every failure)
python3 -I validate_scenarios.py scenarios.txt

# Generate SQL without loading it
python3 -I generate_dml.py scenarios.txt out.sql --as-of 2026-12-01

# Also write the date-shifted JSON, e.g. to check it
python3 -I generate_dml.py scenarios.txt out.sql --as-of 2026-12-01 --dump-json shifted.json
python3 -I validate_scenarios.py shifted.json

# Load a generated SQL file by hand
docker exec -i funder-postgres psql -U funder_admin -d auto_funding_db -v ON_ERROR_STOP=1 < out.sql
```

### Adding more scenarios

1. Write the new records in `scenarios.txt` following the PRD rules (ID formats, date offsets from `generatedAt`, task ownership, event rules).
2. Run `python3 -I validate_scenarios.py scenarios.txt` and fix every failure it lists.
3. Run `./daily_load.sh`.

## Docker commands

```bash
docker compose up -d                 # start, in the background
docker compose ps                    # status and health
docker compose logs -f postgres      # follow the logs
docker compose stop                  # stop; data is kept
docker compose start                 # start again
docker compose down                  # remove the container; data is kept in the pgdata18 volume
docker compose down -v               # remove the container AND the data volume
```

### Rebuilding from scratch

The scripts in `init/` run **only when the data volume is empty**. After you change `init/01-schema.sql`, rebuild:

```bash
docker compose down -v
docker compose up -d
./daily_load.sh
```

To rebuild the schema without deleting the volume:

```bash
docker exec -i funder-postgres psql -U funder_admin -d auto_funding_db \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker exec -i funder-postgres psql -U funder_admin -d auto_funding_db -v ON_ERROR_STOP=1 < init/01-schema.sql
./daily_load.sh
```

## Checking the load

```sql
SELECT status, count(*) FROM applications GROUP BY 1 ORDER BY 2 DESC;
-- PENDING_STIPULATIONS 50, READY_TO_FUND 20, PENDING_AGENT_VERIFICATION 20,
-- FUNDED 8, EXPIRED 6, EXCEPTION_HOLD 4, WITHDRAWN 1, DECLINED 1

SELECT status, count(*) FROM funding_tasks GROUP BY 1 ORDER BY 2 DESC;
-- VERIFIED 471, DISCREPANCY_FLAGGED 50, PENDING_REVIEW 20, EXPIRED 5

SELECT count(*) FROM activity_events;   -- 691
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `port 5432 is already allocated` | Another Postgres is running. Stop it, or change the mapping to `"5433:5432"` in `docker-compose.yml` and connect on 5433. |
| `No such container: funder-postgres` | Run `docker compose up -d` first. |
| `Cannot connect to the Docker daemon` | Start Docker Desktop. |
| `relation "..." does not exist` | The schema wasn't created, probably because the volume already existed. See **Rebuilding from scratch**. |
| `daily_load.sh` stops with validation failures | `scenarios.txt` breaks a PRD rule. Fix the records it lists. The database was not changed. |
| Changes to `01-schema.sql` don't take effect | Init scripts run only on an empty volume. See **Rebuilding from scratch**. |
| Cron job doesn't run on macOS | Give `/usr/sbin/cron` Full Disk Access, and check `daily_load.log`. |
