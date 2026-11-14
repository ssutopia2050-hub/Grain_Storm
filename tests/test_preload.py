import json
from pathlib import Path
import tempfile
import unittest

from grainstorm.context import ContextService
from grainstorm.preload import compact_summary, schedule, wait_for_jobs


class PreloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ContextService(Path(self.temp.name) / 'cache.sqlite3', fetchers={})

    def test_schedule_is_bounded_and_compact(self):
        result = schedule(self.service, 30.34, 76.39, '2024-01-01', '2024-01-02', ['imerg', 'smap'])
        summary = compact_summary(result)
        self.assertEqual(summary['sources']['imerg']['jobs'], {'queued': 2})
        self.assertEqual(summary['sources']['smap']['jobs'], {'queued': 1})
        self.assertNotIn('records', json.dumps(summary))
        with self.assertRaises(ValueError):
            schedule(self.service, 30.34, 76.39, '2023-01-01', '2024-01-02', ['imerg'])

    def test_wait_processes_jobs_and_final_query_is_cached(self):
        result = schedule(self.service, 30.34, 76.39, '2024-01-01', '2024-01-03', ['imerg'])
        ids = compact_summary(result)['sources']['imerg']['job_ids']

        class FakeClient:
            def imerg(inner, job, directory):
                return ([{'date': job['start_date'], 'gpm_precipitation_mm_day': 2}], {'test': True})

        jobs = wait_for_jobs(self.service, ids, concurrency=3, poll_seconds=0, client_factory=FakeClient)
        self.assertTrue(all(job['status'] == 'complete' for job in jobs))
        final = self.service.query(30.34, 76.39, '2024-01-01', '2024-01-03', ['imerg'],
                                   acquire_satellites=False)['sources']['imerg']
        self.assertEqual(final['status'], 'complete')
        self.assertEqual(final['cache_hits'], 3)
        self.assertEqual(final['jobs'], [])


if __name__ == '__main__':
    unittest.main()
