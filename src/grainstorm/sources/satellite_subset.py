"""Bounded satellite subsets. Never fall back to downloading global granules."""
from datetime import date
import json
import math
import netrc
import os
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import requests
import threading

from grainstorm.sources.appeears import AppEEARSClient, APPEEARS_API
from grainstorm.processing.smap import normalize_smap_point_csv, ROOTZONE_SUFFIX, SURFACE_SUFFIX


class CredentialsRequired(RuntimeError):
    pass


class SubsetError(RuntimeError):
    pass


_EARTHDATA_LOGIN_LOCK = threading.Lock()


def credentials():
    user, password = os.getenv('EARTHDATA_USERNAME'), os.getenv('EARTHDATA_PASSWORD')
    if user and password:
        return user, password, 'environment'
    try:
        entry = netrc.netrc(os.getenv('NETRC') or str(Path.home() / '.netrc')).authenticators('urs.earthdata.nasa.gov')
    except (OSError, netrc.NetrcParseError):
        entry = None
    if entry and entry[0] and entry[2]:
        return entry[0], entry[2], 'netrc'
    raise CredentialsRequired('Configure Earthdata credentials on the worker, never in API requests.')


def bounded_download(session, url, path, *, params=None, headers=None, limit=2_000_000):
    """Cap response bytes even if the server ignores the subset constraint."""
    path = Path(path)
    partial = path.with_suffix(path.suffix + '.part')
    try:
        with session.get(url, params=params, headers=headers, timeout=(15, 60), stream=True) as response:
            response.raise_for_status()
            if int(response.headers.get('Content-Length', 0)) > limit:
                raise SubsetError('Subset response exceeded the size limit.')
            size = 0
            with partial.open('wb') as stream:
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > limit:
                        raise SubsetError('Subset response exceeded the size limit.')
                    stream.write(chunk)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def imerg_constraint(lat, lon):
    from grainstorm.context import location_key
    _, x, y = location_key('imerg', lat, lon).split(':')
    variables = ['precipitation', 'randomError', 'precipitation_cnt', 'precipitation_cnt_cond']
    return ';'.join([f'/{v}[0:1:0][{x}:1:{x}][{y}:1:{y}]' for v in variables]
                    + [f'/lon[{x}:1:{x}]', f'/lat[{y}:1:{y}]', '/time[0:1:0]'])


def read_imerg_subset(path, lat, lon, day):
    from netCDF4 import Dataset, num2date
    from grainstorm.context import location_key
    from grainstorm.processing.gpm_imerg import _value_at_point
    mapping = {'precipitation': 'gpm_precipitation_mm_day', 'randomError': 'gpm_random_error_mm_day',
               'precipitation_cnt': 'gpm_valid_half_hourly_count', 'precipitation_cnt_cond': 'gpm_wet_half_hourly_count'}
    with Dataset(path) as ds:
        for name in ['lat', 'lon', 'time', *mapping]:
            if name not in ds.variables or ds.variables[name].size != 1:
                raise SubsetError('IMERG response must contain exactly one cell and one day.')
        center = {name: float(np.asarray(ds.variables[var][:]).item())
                  for name, var in [('latitude', 'lat'), ('longitude', 'lon')]}
        if not all(math.isfinite(v) for v in center.values()) or location_key('imerg', center['latitude'], center['longitude']) != location_key('imerg', lat, lon):
            raise SubsetError('IMERG returned a different grid cell.')
        t = ds.variables['time']
        actual_day = num2date(float(np.asarray(t[:]).item()), t.units, calendar=getattr(t, 'calendar', 'standard')).strftime('%Y-%m-%d')
        if actual_day != day or ds.variables['precipitation'].units != 'mm/day':
            raise SubsetError('IMERG date or units do not match the requested daily product.')
        row = {'date': day, **{column: _value_at_point(ds, name, 0, 0) for name, column in mapping.items()}}
        count = row['gpm_valid_half_hourly_count']
        if count is None or not 1 <= count <= 48 or not count.is_integer():
            row['gpm_precipitation_mm_day'] = None
    return [row], center


class SatelliteClient:
    def __init__(self):
        self._imerg_session = None
        self._smap_client = None

    def imerg(self, job, directory):
        import earthaccess
        if self._imerg_session is None:
            _, _, strategy = credentials()
            # earthaccess keeps authentication in process-global state. Serialize
            # session creation while allowing the bounded downloads themselves
            # to run concurrently.
            with _EARTHDATA_LOGIN_LOCK:
                auth = earthaccess.login(strategy=strategy, persist=False)
                if not auth.authenticated:
                    raise CredentialsRequired('Earthdata authentication failed.')
                self._imerg_session = earthaccess.get_requests_https_session()
        day = job['start_date']
        response = requests.get('https://cmr.earthdata.nasa.gov/search/granules.umm_json', params={
            'short_name': 'GPM_3IMERGDF', 'version': '07',
            'temporal': f'{day}T00:00:00Z,{day}T23:59:59Z', 'page_size': 10}, timeout=30)
        response.raise_for_status()
        items = response.json()['items']
        if len(items) != 1:
            raise SubsetError('Expected one Final IMERG daily granule; it may not be published yet.')
        granule = items[0]['umm']
        links = [u['URL'] for u in granule['RelatedUrls'] if u.get('Subtype') == 'OPENDAP DATA']
        # Only use the provider's current authenticated cloud service.
        links = [u for u in links if urlsplit(u).scheme == 'https' and urlsplit(u).hostname == 'opendap.earthdata.nasa.gov']
        if len(links) != 1:
            raise SubsetError('No unique cloud OPeNDAP URL in NASA catalogue; no bulk fallback.')
        url = links[0].removesuffix('.html') + '.dap.nc4'
        constraint = imerg_constraint(job['latitude'], job['longitude'])
        path = directory / 'imerg.nc4'
        bounded_download(self._imerg_session, url, path, params={'dap4.ce': constraint})
        rows, center = read_imerg_subset(path, job['latitude'], job['longitude'], day)
        return rows, {'provider': 'NASA GES DISC cloud OPeNDAP', 'product': 'GPM_3IMERGDF.07',
                      'granule': granule['GranuleUR'], 'url': links[0], 'constraint': constraint,
                      'selected_grid_cell_center': center, 'time_support': 'UTC day',
                      'requested_point': {'latitude': job['latitude'], 'longitude': job['longitude']},
                      'raw_subset': str(path), 'bytes_downloaded': path.stat().st_size}

    def smap_client(self):
        if self._smap_client is None:
            user, password, _ = credentials()
            client = AppEEARSClient(user, password)
            # Authenticate before recording a potentially ambiguous task POST.
            client._login()
            self._smap_client = client
        return self._smap_client

    def submit_smap(self, job):
        client = self.smap_client()
        task = {'task_type': 'point', 'task_name': f"grainstorm-{job['id']}", 'params': {
            'dates': [{'startDate': date.fromisoformat(job['start_date']).strftime('%m-%d-%Y'),
                       'endDate': date.fromisoformat(job['end_date']).strftime('%m-%d-%Y')}],
            'layers': [{'product': 'SPL4SMGP.008', 'layer': layer} for layer in [ROOTZONE_SUFFIX, SURFACE_SUFFIX]],
            'coordinates': [{'id': 'grain-storm-point', 'latitude': job['latitude'], 'longitude': job['longitude']}]}}
        response = client.session.post(f'{APPEEARS_API}/task', json=task, headers=client._headers(), timeout=60)
        response.raise_for_status()
        return response.json()['task_id']

    def poll_smap(self, job, directory):
        client = self.smap_client()
        task_id = job['task_id']
        task = client._get_json(f'/task/{task_id}', authenticated=True)
        state = str(task.get('status', '')).lower()
        if state in {'error', 'failed', 'cancelled', 'expired'}:
            raise SubsetError('NASA AppEEARS task failed or expired.')
        if state != 'done':
            return None
        bundle = client._get_json(f'/bundle/{task_id}', authenticated=True)
        results = [f for f in bundle.get('files', []) if f['file_name'].endswith('results.csv') and 'SPL4SMGP' in f['file_name']]
        if len(results) != 1:
            raise SubsetError('Expected one SMAP point result table.')
        path = directory / 'smap-results.csv'
        bounded_download(client.session, f"{APPEEARS_API}/bundle/{task_id}/{results[0]['file_id']}",
                         path, headers=client._headers(), limit=10_000_000)
        raw = pd.read_csv(path)
        for column, expected in [('Latitude', job['latitude']), ('Longitude', job['longitude'])]:
            if column not in raw or raw.empty or not np.isclose(pd.to_numeric(raw[column], errors='coerce'), expected, atol=1e-5, rtol=0).all():
                raise SubsetError('SMAP result coordinates do not match the request.')
        metadata = {'provider': 'NASA AppEEARS', 'product': 'SPL4SMGP.008', 'task_id': task_id,
                    'requested_coordinates': {'latitude': job['latitude'], 'longitude': job['longitude']},
                    'requested_dates_utc': {'start': job['start_date'], 'end': job['end_date']},
                    'task_params': task.get('params'),
                    'result_file': {k: results[0].get(k) for k in ('file_name', 'file_id')}}
        meta_path = directory / 'source.metadata.json'
        meta_path.write_text(json.dumps(metadata))
        frame, meta = normalize_smap_point_csv(path, output_csv=directory / 'smap-daily.csv', input_metadata=meta_path)
        from grainstorm.context import _records
        return _records(frame), meta
