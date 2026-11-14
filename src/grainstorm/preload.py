"""Preload a bounded historical context window for a demo or pilot location."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import time

from grainstorm.context import ContextService, SPECS, days_between
from grainstorm.satellite_jobs import SatelliteJobs


TERMINAL = {'complete', 'partial', 'failed', 'auth_required'}


def compact_summary(result):
    return {
        'requested_point': result['requested_point'],
        'start_date': result['start_date'],
        'end_date': result['end_date'],
        'sources': {
            name: {
                'status': data['status'],
                'cached_days': len(data['records']),
                'missing_days': len(data['missing_dates']),
                'invalid_days': len(data['invalid_dates']),
                'fetched_days': data['fetched_days'],
                'jobs': dict(Counter(job['status'] for job in data['jobs'])),
                'job_count': len(data['jobs']),
                'job_ids': [job['id'] for job in data['jobs'][:20]],
                'job_ids_truncated': len(data['jobs']) > 20,
                'errors': data['errors'],
            }
            for name, data in result['sources'].items()
        },
    }


def schedule(service, latitude, longitude, start, end, sources, retry_failed=False):
    days = days_between(start, end)
    if len(days) > 366:
        raise ValueError('One preload is limited to 366 days; use separate season/year windows.')
    return service.query(latitude, longitude, start, end, sources,
                         acquire_satellites=True, retry_failed=retry_failed)


def wait_for_jobs(service, job_ids, concurrency=4, poll_seconds=3, client_factory=None):
    queue = SatelliteJobs(service)
    previous = {}
    while True:
        jobs = [queue.get(ident) for ident in job_ids]
        for job in jobs:
            if previous.get(job['id']) != job['status']:
                print(json.dumps({k: job[k] for k in ('id', 'source', 'status', 'start_date', 'end_date', 'error')}), flush=True)
                previous[job['id']] = job['status']
        if all(job['status'] in TERMINAL for job in jobs):
            return jobs
        processed = queue.run_batch(concurrency, client_factory) if client_factory else queue.run_batch(concurrency)
        if not processed:
            time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='Same SQLite cache path used by the API and worker.')
    parser.add_argument('--latitude', type=float, required=True)
    parser.add_argument('--longitude', type=float, required=True)
    parser.add_argument('--start', required=True, help='Historical start date, YYYY-MM-DD.')
    parser.add_argument('--end', required=True, help='Historical end date, YYYY-MM-DD.')
    parser.add_argument('--sources', nargs='+', choices=list(SPECS), default=['imerg', 'smap', 'era5'])
    parser.add_argument('--wait', action='store_true', help='Process and wait for queued satellite jobs.')
    parser.add_argument('--concurrency', type=int, default=4, help='Concurrent satellite jobs while waiting (1-8).')
    parser.add_argument('--retry-failed', action='store_true', help='Explicitly retry terminal jobs in this window.')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 8:
        parser.error('--concurrency must be between 1 and 8.')
    try:
        service = ContextService(args.db)
        result = schedule(service, args.latitude, args.longitude, args.start, args.end,
                          args.sources, args.retry_failed)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    summary = compact_summary(result)
    print(json.dumps(summary, indent=2, allow_nan=False), flush=True)
    job_ids = sorted({job['id'] for data in result['sources'].values() for job in data['jobs']})
    if args.wait and job_ids:
        jobs = wait_for_jobs(service, job_ids, args.concurrency)
        final = service.query(args.latitude, args.longitude, args.start, args.end,
                              args.sources, acquire_satellites=False)
        print(json.dumps({'final': compact_summary(final),
                          'job_statuses': dict(Counter(job['status'] for job in jobs))},
                         indent=2, allow_nan=False), flush=True)
        if any(job['status'] != 'complete' for job in jobs):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
