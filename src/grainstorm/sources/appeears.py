"""Point-sample NASA/USGS land products through the AppEEARS API.

AppEEARS subsets many land datasets to a point and returns tabular time series
with quality layers where the product provides them. This connector deliberately
keeps native product/layer names and does not combine unlike measurements.
"""

from __future__ import annotations

import json
import getpass
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests


APPEEARS_API = "https://appeears.earthdatacloud.nasa.gov/api"


class AppEEARSException(RuntimeError):
    """Raised when AppEEARS authentication, processing, or download fails."""


class AppEEARSClient:
    def __init__(self, username: str | None = None, password: str | None = None):
        self.username = username or os.getenv("EARTHDATA_USERNAME")
        self.password = password or os.getenv("EARTHDATA_PASSWORD")
        self.session = requests.Session()
        self.token: str | None = None

    def _login(self) -> str:
        if not self.username:
            self.username = input("NASA Earthdata username: ")
        if not self.password:
            self.password = getpass.getpass("NASA Earthdata password: ")
        try:
            response = self.session.post(
                f"{APPEEARS_API}/login",
                auth=(self.username, self.password),
                timeout=30,
            )
            response.raise_for_status()
            self.token = response.json()["token"]
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise AppEEARSException(f"AppEEARS login failed: {exc}") from exc
        return self.token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token or self._login()}"}

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> Any:
        try:
            headers = self._headers() if authenticated else None
            response = self.session.get(
                f"{APPEEARS_API}{path}", headers=headers, params=params, timeout=60
            )
            if response.status_code in {401, 403} and authenticated:
                self.token = self._login()
                response = self.session.get(
                    f"{APPEEARS_API}{path}", headers=self._headers(), params=params, timeout=60
                )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AppEEARSException(f"AppEEARS request failed for {path}: {exc}") from exc

    def list_products(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        """Return currently available products and their coverage metadata."""
        products = self._get_json("/product", params={"limit": limit, "offset": 0})
        return [item for item in products if item.get("Available") and not item.get("Deleted")]

    def list_layers(self, product: str) -> dict[str, Any]:
        """Return the native layer definitions for a product/version ID."""
        return self._get_json(f"/product/{product}")

    def fetch_point_sample(
        self,
        *,
        product: str,
        layers: list[str],
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        output_dir: str | Path,
        poll_seconds: int = 15,
        timeout_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Submit a point extraction and save all returned files plus provenance."""
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Coordinates are out of range.")
        if not layers:
            raise ValueError("Choose at least one product layer.")
        parsed_dates = []
        for value in (start_date, end_date):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dates must use YYYY-MM-DD format.")
            try:
                parsed_dates.append(date.fromisoformat(value))
            except ValueError as exc:
                raise ValueError("Dates must be valid calendar dates.") from exc
        if parsed_dates[0] > parsed_dates[1]:
            raise ValueError("Start date cannot be after end date.")

        task = {
            "task_type": "point",
            "task_name": f"grain-storm-{product.replace('.', '-')}",
            "params": {
                "dates": [{
                    "startDate": parsed_dates[0].strftime("%m-%d-%Y"),
                    "endDate": parsed_dates[1].strftime("%m-%d-%Y"),
                }],
                "layers": [{"product": product, "layer": layer} for layer in layers],
                "coordinates": [{"id": "grain-storm-point", "latitude": latitude, "longitude": longitude}],
            },
        }
        print("Submitting the AppEEARS point-sampling request...", flush=True)
        try:
            submitted = self.session.post(
                f"{APPEEARS_API}/task", json=task, headers=self._headers(), timeout=60
            )
            submitted.raise_for_status()
            task_id = submitted.json()["task_id"]
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise AppEEARSException(f"Could not submit AppEEARS extraction: {exc}") from exc
        print(f"AppEEARS task submitted: {task_id}", flush=True)

        deadline = time.monotonic() + timeout_seconds
        status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            payload = self._get_json(f"/status/{task_id}", authenticated=True)
            status = payload[0] if isinstance(payload, list) and payload else payload
            state = str(status.get("status", "")).lower()
            progress = status.get("progress", {})
            percent = progress.get("summary") if isinstance(progress, dict) else None
            if state != "done":
                progress_text = f" ({percent}% complete)" if percent is not None else ""
                print(f"AppEEARS task status: {state or 'processing'}{progress_text}", flush=True)
            if state == "done":
                break
            if state == "error":
                raise AppEEARSException(f"AppEEARS task {task_id} failed: {status}")
            time.sleep(poll_seconds)
        else:
            raise AppEEARSException(
                f"AppEEARS task {task_id} is still processing; check it later in AppEEARS."
            )

        bundle = self._get_json(f"/bundle/{task_id}", authenticated=True)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        saved_files: list[str] = []
        for item in bundle.get("files", []):
            name = Path(item["file_name"]).name
            response = self.session.get(
                f"{APPEEARS_API}/bundle/{task_id}/{item['file_id']}",
                headers=self._headers(), timeout=180, stream=True,
            )
            try:
                response.raise_for_status()
                path = destination / name
                with path.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            stream.write(chunk)
                saved_files.append(str(path))
            except requests.RequestException as exc:
                raise AppEEARSException(f"Could not download {name}: {exc}") from exc
            finally:
                response.close()

        metadata = {
            "provider": "NASA AppEEARS",
            "task_id": task_id,
            "product": product,
            "layers": layers,
            "requested_coordinates": {"latitude": latitude, "longitude": longitude},
            "requested_dates_utc": {"start": start_date, "end": end_date},
            "files": saved_files,
            "quality_note": "Retain quality layers and product metadata when interpreting values.",
            "task_request": task,
        }
        metadata_path = destination / f"appeears_{task_id}_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        metadata["metadata_file"] = str(metadata_path)
        return metadata
