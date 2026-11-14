"""Durable, single-host satellite job queue. Run beside the API as a worker."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from grainstorm.context import ContextService, SPECS, days_between, location_key, _spans
from grainstorm.sources.satellite_subset import SatelliteClient, CredentialsRequired, credentials


class SatelliteJobs:
    def __init__(self, context):
        self.context = context
        with context.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS satellite_jobs (
                    id TEXT PRIMARY KEY, source TEXT, product TEXT, location TEXT,
                    latitude REAL, longitude REAL, start_date TEXT, end_date TEXT,
                    status TEXT, task_id TEXT, phase TEXT, available_at REAL,
                    lease_until REAL, error TEXT, created_at REAL, updated_at REAL);
                CREATE TABLE IF NOT EXISTS satellite_days (
                    source TEXT, product TEXT, location TEXT, day TEXT, job_id TEXT,
                    PRIMARY KEY (source, product, location, day));
            ''')

    def enqueue(self, source, lat, lon, days, retry=False):
        if source not in {'imerg', 'smap'}:
            raise ValueError('Only IMERG and SMAP use the satellite queue.')
        key, product = location_key(source, lat, lon), SPECS[source]['product']
        now = time.time()
        ids, unreserved = set(), []
        with self.context.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for day in sorted(set(days)):
                row = conn.execute('SELECT job_id FROM satellite_days WHERE source=? AND product=? AND location=? AND day=?',
                                   (source, product, key, day)).fetchone()
                if row:
                    ids.add(row[0])
                else:
                    unreserved.append(day)
            for start, end in _spans(unreserved):
                span = days_between(start, end)
                chunk_size = 1 if source == 'imerg' else 31
                for i in range(0, len(span), chunk_size):
                    chunk, ident = span[i:i+chunk_size], uuid.uuid4().hex
                    conn.execute('INSERT INTO satellite_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (ident, source, product, key, lat, lon, chunk[0], chunk[-1], 'queued', None, None,
                                  now, 0, None, now, now))
                    conn.executemany('INSERT INTO satellite_days VALUES (?,?,?,?,?)',
                                     [(source, product, key, day, ident) for day in chunk])
                    ids.add(ident)
            if retry:
                for ident in ids:
                    # Preserve a submitted AppEEARS task so retries resume it, not duplicate it.
                    conn.execute("UPDATE satellite_jobs SET status='queued', error=NULL, available_at=?, updated_at=? WHERE id=? AND status IN ('failed','partial','auth_required','complete') AND COALESCE(phase,'') != 'submission_uncertain'",
                                 (now, now, ident))
        return [self.get(ident) for ident in sorted(ids)]

    def get(self, ident):
        with self.context.connect() as conn:
            cursor = conn.execute('SELECT * FROM satellite_jobs WHERE id=?', (ident,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError(ident)
            return dict(zip([c[0] for c in cursor.description], row))

    def update(self, ident, **values):
        allowed = {'status', 'task_id', 'phase', 'available_at', 'lease_until', 'error'}
        if not set(values) <= allowed:
            raise ValueError('Invalid job update fields.')
        values['updated_at'] = time.time()
        with self.context.connect() as conn:
            conn.execute('UPDATE satellite_jobs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?',
                         [*values.values(), ident])

    def claim(self, source=None):
        now = time.time()
        with self.context.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # A crash during a POST may have submitted a task without returning its ID.
            # Do not blindly submit another. The named task can be recovered in AppEEARS.
            conn.execute("UPDATE satellite_jobs SET status='failed', phase='submission_uncertain', error='Submission interrupted; recover task ID from AppEEARS before retrying.' WHERE status='running' AND lease_until<? AND source='smap' AND phase='submitting' AND task_id IS NULL", (now,))
            source_sql = ' AND source=?' if source else ''
            parameters = (now, now, source) if source else (now, now)
            row = conn.execute(
                "SELECT id FROM satellite_jobs WHERE ((status IN ('queued','waiting') AND available_at<=?) "
                "OR (status='running' AND lease_until<?))" + source_sql + " ORDER BY created_at LIMIT 1",
                parameters,
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE satellite_jobs SET status='running', lease_until=?, updated_at=? WHERE id=?", (now+600, now, row[0]))
        return self.get(row[0])

    def _run_job(self, job, client):
        client = client or SatelliteClient()
        ident = job['id']
        directory = self.context.db_path.parent / 'subsets' / ident
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if job['source'] == 'imerg':
                result = client.imerg(job, directory)
            elif not job['task_id']:
                # Check credentials before marking a potentially ambiguous remote submission.
                client.smap_client()
                self.update(ident, phase='submitting')
                task_id = client.submit_smap(job)
                self.update(ident, task_id=task_id, phase='polling', status='waiting', available_at=time.time()+15, lease_until=0)
                return self.get(ident)
            else:
                result = client.poll_smap(job, directory)
                if result is None:
                    if time.time() - job['created_at'] > 48*3600:
                        raise RuntimeError('Provider task exceeded worker polling window.')
                    self.update(ident, status='waiting', available_at=time.time()+30, lease_until=0)
                    return self.get(ident)
            rows, metadata = result
            rows = [r for r in rows if job['start_date'] <= r['date'] <= job['end_date']]
            self.context.put(job['source'], job['latitude'], job['longitude'], rows,
                             {'retrieval': 'satellite_subset', 'job_id': ident, 'provider_metadata': metadata,
                              'retrieved_at_utc': datetime.now(timezone.utc).isoformat()})
            stored = self.context._read(job['source'], job['location'], job['start_date'], job['end_date'])
            valid = [r for r in rows if all(json.loads(stored[r['date']][1]).get(v) is not None
                                           for v in SPECS[job['source']]['variables'])]
            complete = len(valid) == len(days_between(job['start_date'], job['end_date']))
            self.update(ident, status='complete' if complete else 'partial', error=None if complete else 'Provider returned incomplete or invalid observations.', lease_until=0)
        except CredentialsRequired:
            self.update(ident, status='auth_required', error='Configure valid Earthdata credentials on the worker and retry.', lease_until=0)
        except Exception as exc:
            current = self.get(ident)
            uncertain = current['phase'] == 'submitting' and current['task_id'] is None
            # Never serialize provider exception messages: these may contain credentials/URLs.
            self.update(ident, status='failed', phase='submission_uncertain' if uncertain else current['phase'],
                        error=('Submission outcome uncertain; recover task ID in AppEEARS.' if uncertain else f'Satellite retrieval failed ({type(exc).__name__}); retry after checking provider access/availability.'), lease_until=0)
        return self.get(ident)

    def run_once(self, client=None):
        job = self.claim()
        return None if job is None else self._run_job(job, client or SatelliteClient())

    def run_batch(self, concurrency=4, client_factory=SatelliteClient):
        """Process one SMAP job and several independent IMERG days concurrently."""
        if not 1 <= concurrency <= 8:
            raise ValueError('Worker concurrency must be between 1 and 8.')
        jobs = []
        smap = self.claim('smap')
        if smap:
            jobs.append(smap)
        while len(jobs) < concurrency:
            imerg = self.claim('imerg')
            if imerg is None:
                break
            jobs.append(imerg)
        if not jobs:
            job = self.claim()
            if job:
                jobs.append(job)
        if not jobs:
            return []
        if len(jobs) == 1:
            return [self._run_job(jobs[0], client_factory())]
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix='grainstorm-satellite') as pool:
            futures = [pool.submit(self._run_job, job, client_factory()) for job in jobs]
            return [future.result() for future in futures]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='Same SQLite path used by the API.')
    parser.add_argument('--once', action='store_true', help='Process one queued job or poll one NASA task, then exit.')
    parser.add_argument('--concurrency', type=int, default=4,
                        help='Concurrent jobs per batch (1-8, default 4; at most one SMAP job per batch).')
    parser.add_argument('--check-auth', action='store_true', help='Check local credential availability without printing secrets.')
    parser.add_argument('--resume-job', help='Resume a failed/auth-required job after fixing access.')
    parser.add_argument('--task-id', help='Recover an uncertain SMAP submission with its existing AppEEARS task ID.')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 8:
        parser.error('--concurrency must be between 1 and 8.')
    if args.check_auth:
        try:
            credentials()
        except CredentialsRequired:
            parser.exit(1, 'Earthdata credentials are not configured. See docs/satellite_context.md.\n')
        print('Local Earthdata credentials found (provider access not yet verified).')
        return
    queue = SatelliteJobs(ContextService(args.db))
    if args.resume_job:
        job = queue.get(args.resume_job)
        if job['status'] in {'running', 'waiting', 'queued'}:
            parser.error('This job is already active.')
        if job['phase'] == 'submission_uncertain' and not args.task_id:
            parser.error('Recover the existing NASA task using --task-id; do not submit it twice.')
        if args.task_id and (job['source'] != 'smap' or not all(c in '0123456789abcdef-' for c in args.task_id.lower()) or len(args.task_id) != 36):
            parser.error('--task-id must be a SMAP AppEEARS task UUID.')
        queue.update(job['id'], status='queued', task_id=args.task_id or job['task_id'],
                     phase='polling' if args.task_id or job['task_id'] else None, available_at=time.time(), error=None)
    print(
        f"Satellite worker ready (concurrency={args.concurrency}). Watching "
        f"{queue.context.db_path} for IMERG/SMAP jobs. "
        "Press Ctrl+C to stop.",
        flush=True,
    )
    while True:
        results = queue.run_batch(args.concurrency)
        for result in results:
            print(json.dumps({k: result[k] for k in ('id', 'source', 'status', 'error')}), flush=True)
        if args.once:
            if not results:
                print('No satellite jobs are currently queued.', flush=True)
            break
        if not results:
            time.sleep(3)


if __name__ == '__main__':
    main()
