# Runbook: the Trading Journal in Docker

How to run, look after and recover the production stack on your own machine. Every command here was run against the real image while writing this. Commands are for PowerShell, from the repository root. The design is in [BLUEPRINT.md](BLUEPRINT.md), section 6.1.

## What runs

One container, `app`, serves the API at `/api` and the web app at `/` on **http://127.0.0.1:8000**. It listens on loopback only: there is no login, so nothing beyond this machine may reach it. Its database is a SQLite file on the named volume `tradingjournal_tj_data` (inside the container: `/data/tj.db`). The container's root filesystem is read-only, it runs as an unprivileged user with no capabilities, and the only places it can write are `/data` and a small `/tmp`.

## Start, stop, update

```powershell
docker compose up -d --build --wait     # build the image, start the container, wait until its healthcheck passes
docker compose ps                       # "Up ... (healthy)"
docker compose logs -f app              # JSON logs, one record per line; Ctrl+C stops watching, not the app
docker compose stop                     # stop it (data stays)
docker compose start                    # start it again
docker compose down                     # remove the container (the volume, and so your data, stays)
```

To update, get the new code and run `docker compose up -d --build --wait` again. The app applies its database migrations itself as it starts, and your data stays on the volume. **`docker compose down -v` deletes the volume, and your journal with it.** It asks nothing.

## Settings

Put them in a `.env` file next to `docker-compose.yml` (see `.env.example`), or in the environment.

| Variable | Default | What it does |
|----------|---------|--------------|
| `APP_PORT` | `8000` | The port on 127.0.0.1 |
| `APP_TIMEZONE` | `UTC` | Which calendar day a trade falls on. Set your own, for example `America/New_York`. Changing it re-buckets history |
| `FEEDS_MODE` | `off` | `live` to read ForexFactory and Google Calendar. Nothing is fetched until you say so |
| `GCAL_ICAL_URL` | unset | Your calendar's **secret** iCal address. Treat it as a password |
| `LOG_LEVEL` | `INFO` | |
| `MAX_REQUEST_BYTES` | `1048576` | The largest request body the API accepts, answered with 413 beyond it |
| `TJ_IMAGE_TAG` | `local` | The tag of the image compose builds and runs |

After changing a setting, `docker compose up -d --wait` recreates the container with it.

The secret calendar address is passed to the container as an environment variable, so `docker inspect` on this machine shows it. That is acceptable for a single-user machine and not for a shared one. If it ever leaks, reset it in Google Calendar's settings and put the new one here. The app never returns it from the API, shows it on a screen or writes it to a log.

## Health

The container reports itself healthy when `GET /api/health` answers 200 with `{"status": "ok"}`, checked every 10 seconds, and unhealthy after three misses in a row. Each probe sends the request id `healthcheck`, so in the logs it is easy to tell from your own use: `docker compose logs app | Select-String '"request_id": "healthcheck"'` finds them, and filtering them out leaves only real requests. `GET /api/ready` is the stricter question: the database answers and the schema is at the version the code expects.

```powershell
docker inspect --format "{{.State.Health.Status}}" tradingjournal-app-1
curl.exe http://127.0.0.1:8000/api/ready
```

## Back up and restore

A backup is a consistent copy of the database, taken while the app runs (SQLite's online backup, checked for integrity before it is reported). It is written to `/data/backups` on the volume, so it survives the container, and you copy it somewhere safe:

```powershell
docker compose exec app python -m app.tools.backup --to /data/backups
# {"backup": "/data/backups/tj-20261014T022256Z.db", "bytes": 94208, "integrity": "ok", "rows": {"trades": 1, ...}}

docker compose cp app:/data/backups ./backups      # to a folder outside the volume
```

A backup on the same disk as the data protects against a mistake, not against a dead disk: copy the `backups` folder elsewhere as well.

To restore, stop the app, put a backup in place from a throwaway container on the same volume, and start it again. This replaces the current database:

```powershell
docker compose stop app
docker compose run --rm --no-deps -v "${PWD}/backups:/backups:ro" app python -c "
import os, shutil
for suffix in ('-wal', '-shm'):
    if os.path.exists('/data/tj.db' + suffix):
        os.unlink('/data/tj.db' + suffix)
shutil.copyfile('/backups/tj-20261014T022256Z.db', '/data/tj.db')
"
docker compose up -d --wait
```

(The two `-wal` and `-shm` files are SQLite's write-ahead log of the old database; they must not outlive the file they belong to.) In Git Bash, prefix these commands with `MSYS_NO_PATHCONV=1` so `/data` is not rewritten as a Windows path.

## When something is wrong

| Symptom | Look at | Likely cause and fix |
|---------|---------|----------------------|
| `up --wait` times out, container `unhealthy` | `docker compose logs app` | A startup error: a bad setting (the first line of the log names it), or the volume is not writable. Fix the setting and `up -d --wait` again |
| `port is already allocated` | | Something else uses 8000. Set `APP_PORT=8001` |
| Calendar shows "Rate limited" for the news | the Sources card | ForexFactory limits downloads per address. The stored events are kept and the app backs off 15, 30, 60, then 120 minutes. Press "Sync now" no more than every few minutes |
| Calendar shows "Failed: HTTP 404" for Google | the Sources card | The secret address was reset or mistyped. Copy the current one from Google Calendar's settings into `.env` |
| Days are off by one | `APP_TIMEZONE` | The server buckets days in this zone, which defaults to UTC |
| A request is refused with 413 | | The server accepts bodies up to 1 MiB (`MAX_REQUEST_BYTES`). The journal's own requests are far smaller |
| Everything looks stale after an update | the browser | Reload the page: the new build has new file names, and the page you have open is the old one |

## Verifying a deployment

`python scripts/verify.py 4 --backend compose` builds the image, runs the whole suite against it in containers, and then starts a second stack from `docker-compose.yml` alone (production settings, an empty volume), writes through the browser, replaces the container, backs the database up, and checks that the data and the backup are still there. It also inspects every container it starts: healthy, not root, read-only root filesystem, no capabilities, loopback only, one volume. Its evidence is `logs/phase_4.log`, `artifacts/phase_4/metrics.json` and `artifacts/phase_4/screenshots/`.
