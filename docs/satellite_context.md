# Satellite context: setup and operation

The API queues missing satellite dates; a separate worker retrieves small
subsets and stores normalized rows in the shared SQLite cache. Run commands
from the Grain_Storm project root in the existing Python virtual environment.
Both processes must use the same `GRAINSTORM_CACHE_DB` (default:
`data/cache/environment.sqlite3`). No new packages are required beyond the
project's existing dependencies. The module commands work without reinstalling;
`python -m pip install -e .` also registers `grainstorm-satellite-worker`.

## First-time Earthdata setup

Credentials belong on the backend machine, not in frontend requests or chat.
The worker accepts `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` from its
environment, or Earthdata credentials in the standard local `.netrc` file.
For interactive setup through the already-installed Earthdata client:

```bash
python -c 'import earthaccess; earthaccess.login(strategy="interactive", persist=True)'
python -m grainstorm.satellite_jobs --check-auth
```

The first command prompts locally and persists credentials; keep the resulting
credential file private. `--check-auth` only checks whether credentials exist;
it does not verify provider access. GES DISC and AppEEARS may require one-time
application authorization or acceptance of data-use agreements in Earthdata.
The API and worker never prompt for passwords during a data request.

## Start the service

In one terminal:

```bash
uvicorn grainstorm.api:app --reload
```

In another terminal with the same virtual environment:

```bash
python -m grainstorm.satellite_jobs --concurrency 4
```

Run one satellite worker process for this prototype. It submits/polls at most one
SMAP task per batch while processing independent IMERG days concurrently.
Concurrency defaults to 4 and is capped at 8. Requests return immediately after
queueing satellite work (ERA5/POWER fetches still run synchronously). Jobs are
durable; if the worker is stopped they remain queued. To process one job or
poll one submitted task and then exit, add `--once`.

On Render, the API automatically starts this single-host worker inside the one
Uvicorn service. If a configured `/var/data` path is not writable because no
persistent disk is attached, it logs a warning and uses
`/tmp/grainstorm/environment.sqlite3`. That cache is intentionally ephemeral
and resets when Render replaces or restarts the instance. Set
`GRAINSTORM_EMBEDDED_WORKER=false` only when deploying a separate worker that
shares a durable database. The embedded worker processes four jobs at a time by
default; `GRAINSTORM_WORKER_CONCURRENCY` can override this from 1 through 8.

The worker prints a ready message and then waits. It only prints another line
when a context request queues work or a job changes state. A quiet terminal
after the ready message means the worker is healthy and idle.

Try a one-day request that is outside the originally cached IMERG coverage:

```bash
curl -s http://127.0.0.1:8000/v1/context \
  -H 'Content-Type: application/json' \
  --data-binary @examples/satellite_context_request.json
```

The response includes `sources.imerg.jobs`. Check each job using
`GET /v1/context/jobs/{job_id}`, substituting its actual returned ID. Repeat the
original context request after the jobs finish; completed days now come from
the cache. A cache hit does not submit another job. SMAP may take several
minutes at NASA; waiting is represented explicitly rather than blocking HTTP.

## States and retries

| Job status | Meaning |
|---|---|
| `queued` | Waiting for the local worker |
| `running` | Worker is retrieving or processing the subset |
| `waiting` | NASA AppEEARS is processing a saved task ID |
| `complete` | All requested daily variables were cached |
| `partial` | Provider returned missing or invalid daily observations |
| `auth_required` | Worker has no usable local credentials |
| `failed` | Provider access, availability, response validation, or processing failed |

Partial/failed jobs do not retry endlessly. After fixing access, repeat the
context request with `retry_failed: true`, or use the CLI's `--retry-failed`.
An operator can also use `python -m grainstorm.satellite_jobs --resume-job ID`.
Failed jobs retain already-cached successful days and any known NASA task ID.
The worker polls SMAP for up to 48 hours, after which explicit retry is needed.

A crash or timeout during task submission can leave its outcome uncertain.
Such a job is not automatically resubmitted. Find the task named
`grainstorm-{job_id}` in AppEEARS, then recover it using
`--resume-job ID --task-id NASA_TASK_UUID`. This avoids silently duplicating a
NASA job. Polling state and ordinary queued work survive process restarts.

`POST /v1/plans` with `weather_source.provider: "imerg_era5"` returns HTTP 202
with job details while required IMERG acquisition is active. No plan is computed
yet. Retry the same request after completion. Terminal missing/invalid coverage
returns HTTP 422; ERA5 rainfall is never substituted for missing IMERG rainfall.

## Data contracts and limits

- IMERG: discover `GPM_3IMERGDF` version `07` through CMR; use the catalogue's
  Earthdata Cloud OPeNDAP URL with DAP4 slices for a single time/lon/lat cell.
  Retain precipitation, error, counts, coordinates, and time. Confirm the returned
  date, cell, shape, and rainfall units before ingestion. Maximum response: 2 MB
  per day. A missing service or rejected subset never triggers a global download.
- SMAP: request `SPL4SMGP.008` surface and root-zone layers through AppEEARS.
  Group missing consecutive dates into at most 31-day tasks. Keep the original
  result CSV and task/file provenance, validate requested coordinates, and apply
  the existing daily mean/count normalizer. Maximum result CSV: 10 MB per task.
- Requests are historical. Final IMERG is not a real-time forecast and recent
  dates may be unpublished. Missing observations remain missing.
- SMAP volumetric moisture is regional context, not soil nutrients or an
  automatic conversion to plant-available water. Raw SMAP CSV columns are retained;
  daily aggregation applies range checks, not a new comprehensive product-QA model.
- Subsets live beside the database under `subsets/{job_id}`. This directory and
  the database are ignored by Git. Cache values retain source/version, native
  IMERG cell, requested point, units, dates, and retrieval provenance.
- Satellite day reservations prevent overlapping jobs from repeating the same
  location/product/day. IMERG shares native cells; SMAP shares exact requested
  points. No global data download or yearly archive preload is performed.
- SQLite and job leases support local development. Distributed workers, public
  API authentication/rate limits, automatic retention, and full operational
  recovery tooling remain deployment work.

## Preload a selected season

Use preloading for known demo/pilot coordinates instead of waiting during a
presentation. It stores the same small point/cell records used by on-demand
requests and skips dates already in the cache:

```bash
python -m grainstorm.preload \
  --latitude 30.34 --longitude 76.39 \
  --start 2024-04-01 --end 2024-09-30 \
  --sources imerg smap era5 \
  --wait --concurrency 4
```

Without `--wait`, the command queues satellite gaps for the persistent worker
and exits. `--wait` lets the preload process act as an additional safe worker
until its own jobs reach terminal states. Overlapping worker/API requests reuse
day reservations, so they do not create duplicate downloads. A preload is
limited to 366 days; split longer histories into meaningful seasons/years.

## Verification

Offline tests exercise subset bytes/shape/time/unit checks, SMAP normalization,
overlap deduplication, restart recovery, missing credentials, partial results,
and context/planner status responses. The authenticated IMERG path was also
live-verified for 2024-01-04 at 30.34, 76.39: NASA returned a 42 KB one-cell
subset, the worker cached the valid daily record, and the next query was a cache
hit. The automated SMAP path was live-verified for 2024-02-01: the task ID
survived asynchronous polling, eight sub-daily observations were normalized,
and the next request returned a cache hit with no new job.

Implementation references: [NASA cloud OPeNDAP tutorial](https://github.com/nasa/gesdisc-tutorials/blob/main/notebooks/How_to_Access_Cloud_OPeNDAP_Granules_Using_Python.ipynb)
and [NASA AppEEARS API documentation](https://appeears.earthdatacloud.nasa.gov/api/).
