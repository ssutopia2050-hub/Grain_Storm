"""Offline integration tests for coverage, reuse, provenance and planner inputs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from fastapi.testclient import TestClient

from grainstorm.api import app, get_context_service
from grainstorm.context import ContextService, days_between


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'context.sqlite3'
        self.fetch = Mock(side_effect=self.weather)
        self.service = ContextService(self.path, {'era5': self.fetch}, auto_acquire=False)

    @staticmethod
    def weather(lat, lon, start, end):
        return pd.DataFrame([{'date': d, 'rain_mm': 99, 'et0_mm': 2}
                             for d in days_between(start, end)]), {'test': 'mock'}, {}

    def query(self, start='2024-01-01', end='2024-01-03', sources=('era5',), **kwargs):
        return self.service.query(30.34, 76.39, start, end, sources, **kwargs)['sources']

    def seed(self, source, rows, **kwargs):
        self.service.put(source, 30.34, 76.39, rows, {'test': 'fixture'}, **kwargs)

    def test_repeat_and_overlapping_requests_reuse_persistent_cache(self):
        self.assertEqual(self.query()['era5']['fetched_days'], 3)
        self.service = ContextService(self.path, {'era5': self.fetch}, auto_acquire=False)
        cached = self.query()['era5']
        self.assertEqual(cached['cache_hits'], 3)
        self.assertEqual(cached['provenance'][0]['metadata']['provider_metadata'], {'test': 'mock'})
        self.assertEqual(self.fetch.call_count, 1)
        self.query(end='2024-01-05')
        self.assertEqual(self.fetch.call_args.args[-2:], ('2024-01-04', '2024-01-05'))

    def test_only_missing_disjoint_spans_are_fetched(self):
        self.seed('era5', [{'date': '2024-01-02', 'rain_mm': 0, 'et0_mm': 1}])
        self.query()
        self.assertEqual([c.args[-2:] for c in self.fetch.call_args_list],
                         [('2024-01-01', '2024-01-01'), ('2024-01-03', '2024-01-03')])

    def test_imerg_cell_reuse_and_smap_point_separation(self):
        self.seed('imerg', [{'date': '2024-01-01', 'gpm_precipitation_mm_day': 4}])
        self.seed('smap', [{'date': '2024-01-01', 'soil_moisture_rootzone_m3_m3': .2,
                            'soil_moisture_surface_m3_m3': .1}])
        result = self.service.query(30.36, 76.38, '2024-01-01', '2024-01-01', ['imerg', 'smap'])['sources']
        self.assertEqual(result['imerg']['status'], 'complete')
        self.assertEqual(result['smap']['status'], 'acquisition_required')
        adjacent = self.service.query(30.41, 76.39, '2024-01-01', '2024-01-01', ['imerg'])['sources']['imerg']
        self.assertEqual(adjacent['records'], [])
        self.fetch.assert_not_called()

    def test_invalid_values_stay_missing_and_duplicates_are_atomic(self):
        self.seed('imerg', [{'date': '2024-01-01', 'gpm_precipitation_mm_day': -999}])
        result = self.query(end='2024-01-01', sources=['imerg'])['imerg']
        self.assertIsNone(result['records'][0]['gpm_precipitation_mm_day'])
        self.assertEqual(result['invalid_dates'], ['2024-01-01'])
        self.assertEqual(result['status'], 'partial')
        with self.assertRaises(ValueError):
            self.seed('imerg', [{'date': '2024-01-02', 'gpm_precipitation_mm_day': 1}] * 2)
        self.assertEqual(self.query(sources=['imerg'])['imerg']['missing_dates'], ['2024-01-02', '2024-01-03'])

    def test_expired_or_forced_refresh_fetches_again(self):
        self.seed('era5', [{'date': '2024-01-01', 'rain_mm': 0, 'et0_mm': 1}], ttl_seconds=-1)
        self.query(end='2024-01-01')
        self.query(end='2024-01-01', refresh=True)
        self.assertEqual(self.fetch.call_count, 2)

    def test_upstream_failure_does_not_serve_stale_or_zero(self):
        self.seed('era5', [{'date': '2024-01-01', 'rain_mm': 0, 'et0_mm': 1}], ttl_seconds=-1)
        self.fetch.side_effect = RuntimeError('https://example.invalid?secret=private')
        result = self.query(end='2024-01-01')['era5']
        self.assertEqual(result['records'], [])
        self.assertEqual(result['status'], 'upstream_error')
        self.assertNotIn('private', json.dumps(result))

    def test_future_and_unsupported_requests_do_not_fetch(self):
        for kwargs in ({'end': '2999-01-01'}, {'sources': ['era5', 'unknown']}, {'sources': ['era5', 'era5']}):
            with self.assertRaises(ValueError):
                self.query(**kwargs)
        self.fetch.assert_not_called()

    def test_power_uses_compact_dates_and_preserves_negative_temperature(self):
        fetch = Mock(return_value=(pd.DataFrame([{'date': pd.Timestamp('2024-01-01'),
            'T2M': -5, 'PRECTOTCORR': 0, 'RH2M': 50}]), {'test': 'POWER'}, {}))
        self.service.fetchers['power'] = fetch
        result = self.query(end='2024-01-01', sources=['power'])['power']
        self.assertEqual(fetch.call_args.args[-2:], ('20240101', '20240101'))
        self.assertEqual(result['records'][0]['T2M'], -5)

    def test_import_requires_matching_product_and_grid_provenance(self):
        path = Path(self.temp.name) / 'imerg.csv'
        path.write_text('date,gpm_precipitation_mm_day\n2024-01-01,4\n')
        meta = {'requested_point': {'latitude': 30.34, 'longitude': 76.39},
                'selected_grid_cell_center': {'latitude': 30.35, 'longitude': 76.35},
                'source_manifest': {'short_name': 'GPM_3IMERGDF', 'version': '06'}}
        sidecar = path.with_suffix('.metadata.json')
        sidecar.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            self.service.import_csv('imerg', path)
        meta['source_manifest']['version'] = '07'
        sidecar.write_text(json.dumps(meta))
        self.assertEqual(self.service.import_csv('imerg', path)['imported_days'], 1)
        self.assertEqual(self.query(end='2024-01-01', sources=['imerg'])['imerg']['records'][0]['gpm_precipitation_mm_day'], 4)
        meta['selected_grid_cell_center']['latitude'] = 31.35
        sidecar.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            self.service.import_csv('imerg', path)

    def test_api_lookback_and_missing_satellite_coverage(self):
        app.dependency_overrides[get_context_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.clear)
        with TestClient(app) as client:
            body = {'latitude': 30.34, 'longitude': 76.39, 'end_date': '2024-01-03', 'lookback_days': 3, 'acquire_satellites': False}
            response = client.post('/v1/context', json=body)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['start_date'], '2024-01-01')
            self.assertEqual(data['sources']['era5']['status'], 'complete')
            self.assertTrue(data['sources']['imerg']['acquisition_required'])
            body['start_date'] = '2024-01-01'
            self.assertEqual(client.post('/v1/context', json=body).status_code, 422)

    def test_planner_uses_only_imerg_rain_and_rejects_incomplete_coverage(self):
        self.seed('imerg', [{'date': day, 'gpm_precipitation_mm_day': 4}
                            for day in days_between('2024-01-01', '2024-01-04')])
        request = {
            'field': {'area_ha': 1, 'soil_water_capacity_mm': 100, 'initial_soil_water_mm': 10,
                      'initial_mineral_n_kg_ha': 50},
            'crop_catalog': {'demo': {'duration_days': 4, 'stage_days': [1, 1, 1, 1], 'stage_kc': [1, 1, 1, 1],
                                      'net_soil_n_change_kg_ha': 0}},
            'scenarios': [{'name': 'Pipeline test only', 'start_date': '2024-01-01', 'crops': ['demo']}],
            'weather_source': {'provider': 'imerg_era5', 'latitude': 30.34, 'longitude': 76.39,
                               'start_date': '2024-01-01', 'end_date': '2024-01-04'},
        }
        with patch('grainstorm.api.get_context_service', return_value=self.service), TestClient(app) as client:
            response = client.post('/v1/plans', json=request)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['report']['scenarios'][0]['total_rain_mm'], 16)
            self.assertIsNone(result['weather_metadata']['rainfall_fallback'])
            request['weather_source']['end_date'] = '2024-01-05'
            response = client.post('/v1/plans', json=request)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()['detail']['sources']['imerg']['missing_dates'], ['2024-01-05'])


if __name__ == '__main__':
    unittest.main()
