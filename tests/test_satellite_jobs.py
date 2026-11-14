"""Offline subset and queue integration tests: no Earthdata account required."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from netCDF4 import Dataset, date2num
import pandas as pd

from grainstorm.api import app, get_context_service
from grainstorm.context import ContextService
from grainstorm.satellite_jobs import SatelliteJobs
from grainstorm.sources.satellite_subset import (SatelliteClient, CredentialsRequired, SubsetError,
                                                 bounded_download, imerg_constraint, read_imerg_subset)


class SatelliteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ContextService(Path(self.temp.name) / 'cache.sqlite3', fetchers={})
        self.queue = SatelliteJobs(self.service)

    def enqueue(self, source='imerg', days=('2024-01-01',)):
        return self.queue.enqueue(source, 30.34, 76.39, days)

    def test_overlaps_reuse_jobs_and_claims_are_exclusive(self):
        first = self.enqueue(days=['2024-01-01', '2024-01-02'])
        overlap = self.queue.enqueue('imerg', 30.35, 76.35, ['2024-01-02', '2024-01-03'])
        self.assertEqual(len({j['id'] for j in first + overlap}), 3)
        # Independent queue instances emulate separate requests/process connections.
        other = SatelliteJobs(ContextService(self.service.db_path, fetchers={}))
        with ThreadPoolExecutor(2) as pool:
            claimed = list(pool.map(lambda q: q.claim(), [self.queue, other]))
        self.assertEqual(len({j['id'] for j in claimed}), 2)

    def test_imerg_batch_is_parallel_and_bounded(self):
        self.enqueue(days=['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
        state = {'active': 0, 'maximum': 0}
        lock = threading.Lock()

        class FakeClient:
            def imerg(inner, job, directory):
                with lock:
                    state['active'] += 1
                    state['maximum'] = max(state['maximum'], state['active'])
                time.sleep(.03)
                with lock:
                    state['active'] -= 1
                return ([{'date': job['start_date'], 'gpm_precipitation_mm_day': 1}], {})

        results = self.queue.run_batch(4, FakeClient)
        self.assertEqual(len(results), 4)
        self.assertGreater(state['maximum'], 1)
        self.assertTrue(all(job['status'] == 'complete' for job in results))
        with self.assertRaises(ValueError):
            self.queue.run_batch(9, FakeClient)

    def test_success_is_cached_and_next_request_does_not_enqueue(self):
        initial = self.service.query(30.34, 76.39, '2024-01-01', '2024-01-01', ['imerg'])
        self.assertEqual(initial['sources']['imerg']['status'], 'acquisition_pending')
        client = Mock()
        client.imerg.return_value = ([{'date': '2024-01-01', 'gpm_precipitation_mm_day': 5}], {'test': 'subset'})
        self.assertEqual(self.queue.run_once(client)['status'], 'complete')
        repeated = self.service.query(30.34, 76.39, '2024-01-01', '2024-01-01', ['imerg'])['sources']['imerg']
        self.assertEqual(repeated['status'], 'complete')
        self.assertEqual(repeated['jobs'], [])
        self.assertEqual(repeated['records'][0]['gpm_precipitation_mm_day'], 5)
        self.assertIsNone(self.queue.run_once(client))

    def test_smap_task_survives_restart_and_is_polled_not_resubmitted(self):
        self.enqueue('smap')
        client = Mock()
        client.submit_smap.return_value = 'existing-task-id'
        job = self.queue.run_once(client)
        self.assertEqual(job['status'], 'waiting')
        self.queue.update(job['id'], available_at=0)
        client.poll_smap.return_value = ([{'date': '2024-01-01', 'soil_moisture_rootzone_m3_m3': .2,
                                           'soil_moisture_surface_m3_m3': .1}], {'task_id': job['task_id']})
        restarted = SatelliteJobs(ContextService(self.service.db_path))
        self.assertEqual(restarted.run_once(client)['status'], 'complete')
        client.submit_smap.assert_called_once()
        self.assertEqual(client.poll_smap.call_args.args[0]['task_id'], 'existing-task-id')

    def test_missing_credentials_and_failures_are_explicit_and_sanitized(self):
        job = self.enqueue()[0]
        client = Mock()
        client.imerg.side_effect = CredentialsRequired('secret')
        result = self.queue.run_once(client)
        self.assertEqual(result['status'], 'auth_required')
        self.assertNotIn('secret', result['error'])
        self.queue.enqueue('imerg', 30.34, 76.39, ['2024-01-01'], retry=True)
        client.imerg.side_effect = RuntimeError('token=private')
        self.assertEqual(self.queue.run_once(client)['status'], 'failed')
        self.assertNotIn('private', json.dumps(self.queue.get(job['id'])))

    def test_partial_result_is_not_zero_or_automatically_resubmitted(self):
        self.enqueue()
        client = Mock()
        client.imerg.return_value = ([], {})
        self.assertEqual(self.queue.run_once(client)['status'], 'partial')
        result = self.service.query(30.34, 76.39, '2024-01-01', '2024-01-01', ['imerg'])['sources']['imerg']
        self.assertEqual(result['records'], [])
        self.assertEqual(result['jobs'][0]['status'], 'partial')
        self.assertIsNone(self.queue.run_once(client))

    def test_interrupted_smap_submission_is_not_duplicated(self):
        job = self.enqueue('smap')[0]
        self.queue.update(job['id'], status='running', phase='submitting', lease_until=0)
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.get(job['id'])['phase'], 'submission_uncertain')
        self.queue.enqueue('smap', 30.34, 76.39, ['2024-01-01'], retry=True)
        self.assertEqual(self.queue.get(job['id'])['status'], 'failed')

    def test_api_progress_and_plan_pending_response(self):
        app.dependency_overrides[get_context_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.clear)
        with TestClient(app) as http:
            response = http.post('/v1/context', json={'latitude':30.34, 'longitude':76.39,
                'start_date':'2024-01-01', 'end_date':'2024-01-01', 'sources':['imerg']})
            job = response.json()['sources']['imerg']['jobs'][0]
            self.assertEqual(http.get('/v1/context/jobs/'+job['id']).json()['status'], 'queued')
            self.assertEqual(http.get('/v1/context/jobs/unknown').status_code, 404)
            self.service.put('era5',30.34,76.39,[{'date':'2024-01-01','rain_mm':99,'et0_mm':2}],{})
            with patch('grainstorm.api.get_context_service', return_value=self.service):
                pending = http.post('/v1/plans', json={'field':{},'crop_catalog':{},'scenarios':[],
                    'weather_source':{'provider':'imerg_era5','latitude':30.34,'longitude':76.39,
                                      'start_date':'2024-01-01','end_date':'2024-01-01'}})
            self.assertEqual(pending.status_code,202)
            self.assertNotIn('report', pending.json())

    def test_download_stops_oversize_stream_and_removes_partial(self):
        response = Mock()
        response.headers = {}
        response.iter_content.return_value = [b'a'*6, b'b'*6]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        session = Mock()
        session.get.return_value = response
        path = Path(self.temp.name)/'subset.nc4'
        with self.assertRaises(SubsetError):
            bounded_download(session, 'https://example.invalid', path, limit=10)
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix('.nc4.part').exists())

    def make_netcdf(self, day='2024-01-01', longitude=76.35, units='mm/day', count=48):
        path = Path(self.temp.name)/'test.nc4'
        with Dataset(path,'w') as ds:
            for dim in ['time','lon','lat']:
                ds.createDimension(dim,1)
                ds.createVariable(dim,'f8',(dim,))
            ds['lat'][:] = 30.35
            ds['lon'][:] = longitude
            ds['time'].units = 'days since 1980-01-06 00:00:00Z'
            ds['time'][:] = date2num(datetime.fromisoformat(day),ds['time'].units)
            for name,value in [('precipitation',5),('randomError',2),('precipitation_cnt',count),('precipitation_cnt_cond',3)]:
                var=ds.createVariable(name,'f4',('time','lon','lat'),fill_value=-9999)
                var.units = units if name=='precipitation' else 'count'
                var[:] = value
        return path

    def test_imerg_constraints_and_real_netcdf_parsing(self):
        constraint=imerg_constraint(30.34,76.39)
        self.assertIn('/precipitation[0:1:0][2563:1:2563][1203:1:1203]',constraint)
        rows,center=read_imerg_subset(self.make_netcdf(),30.34,76.39,'2024-01-01')
        self.assertEqual(rows[0]['gpm_precipitation_mm_day'],5)
        self.assertAlmostEqual(center['latitude'],30.35)
        for kwargs in [{'day':'2024-01-02'},{'longitude':77.35},{'units':'mm/hr'}]:
            with self.assertRaises(SubsetError):
                read_imerg_subset(self.make_netcdf(**kwargs),30.34,76.39,'2024-01-01')
        rows,_=read_imerg_subset(self.make_netcdf(count=0),30.34,76.39,'2024-01-01')
        self.assertIsNone(rows[0]['gpm_precipitation_mm_day'])

    def test_imerg_uses_cmr_service_and_bounded_constrained_download(self):
        client=SatelliteClient()
        client._imerg_session=Mock()
        response=Mock()
        url='https://opendap.earthdata.nasa.gov/collections/example/granules/example.nc4'
        response.json.return_value={'items':[{'umm':{'GranuleUR':'example','RelatedUrls':[{'Subtype':'OPENDAP DATA','URL':url}]}}]}
        job=self.enqueue()[0]
        with patch('grainstorm.sources.satellite_subset.requests.get',return_value=response), \
             patch('grainstorm.sources.satellite_subset.bounded_download') as download:
            def write_subset(session,url,path,**kwargs):
                Path(path).write_bytes(self.make_netcdf().read_bytes())
            download.side_effect=write_subset
            rows,metadata=client.imerg(job,Path(self.temp.name))
        self.assertEqual(rows[0]['gpm_precipitation_mm_day'],5)
        self.assertEqual(download.call_args.args[1],url+'.dap.nc4')
        self.assertIn('dap4.ce',download.call_args.kwargs['params'])

    def test_smap_bundle_is_normalized_and_coordinates_checked(self):
        client=SatelliteClient()
        mock=Mock()
        client._smap_client=mock
        job=self.enqueue('smap')[0]
        job['task_id']='test'
        mock._get_json.side_effect=[{'status':'done','params':{}},{'files':[{'file_name':'SPL4SMGP-results.csv','file_id':'file'}]}]
        def download(session,url,path,**kwargs):
            pd.DataFrame({'Latitude':[30.34,30.34], 'Longitude':[76.39,76.39],
                'Date':['2024-01-01 01:30:00 UTC','2024-01-01 04:30:00 UTC'],
                'SPL4SMGP_008_Geophysical_Data_sm_rootzone':[.2,.4],
                'SPL4SMGP_008_Geophysical_Data_sm_surface':[.1,-9999]}).to_csv(path,index=False)
        with patch('grainstorm.sources.satellite_subset.bounded_download',side_effect=download):
            rows,meta=client.poll_smap(job,Path(self.temp.name))
        self.assertEqual(rows[0]['soil_moisture_rootzone_m3_m3'],.3)
        self.assertEqual(rows[0]['surface_observations'],1)
        self.assertEqual(meta['product'],'SPL4SMGP.008')


if __name__=='__main__':
    unittest.main()
