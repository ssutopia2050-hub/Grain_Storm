"""HTTP API for the Grain Storm planning engine."""

from contextlib import asynccontextmanager
from typing import Any, Literal
from datetime import date, timedelta
import logging
import os
import threading
import time

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from grainstorm.planner import simulate_scenarios
from grainstorm.context import ContextService
from grainstorm.processing.planner_weather import merge_imerg_weather
from grainstorm.sources.era5 import Era5Error, fetch_daily_era5_weather
from grainstorm.crops import PROFILE_VERSION, SOURCES, get_profile, list_profiles, planner_template
from grainstorm.sources.gaez import GaezError, fetch_location_suitability
from grainstorm.sources.gaez_calendar import fetch_location_crop_calendars
from grainstorm.sources.gaez_yield import fetch_location_yield_baselines
from grainstorm.sources.ssurgo import SsurgoError, fetch_us_soil_context
from grainstorm.sources.nass import NassError, fetch_us_crop_statistics
from grainstorm.rotation_advice import build_rotation_advice


CropId = Literal[
    "grain_maize", "grain_soybean", "wheat", "sorghum", "chickpea", "sunflower"
]


LOGGER = logging.getLogger(__name__)
_embedded_worker_started = False
_embedded_worker_lock = threading.Lock()


def _run_embedded_satellite_worker() -> None:
    """Run the single-host queue beside Render's one Uvicorn process."""
    try:
        from grainstorm.satellite_jobs import SatelliteJobs

        queue = SatelliteJobs(ContextService())
        LOGGER.info("Embedded satellite worker is watching %s.", queue.context.db_path)
        while True:
            if not queue.run_batch(concurrency=2):
                time.sleep(3)
    except Exception:
        LOGGER.exception("Embedded satellite worker stopped unexpectedly.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _embedded_worker_started
    enabled = os.environ.get("GRAINSTORM_EMBEDDED_WORKER", "true").lower() not in {
        "0", "false", "no", "off",
    }
    if os.environ.get("RENDER") and enabled:
        with _embedded_worker_lock:
            if not _embedded_worker_started:
                threading.Thread(
                    target=_run_embedded_satellite_worker,
                    name="grainstorm-satellite-worker",
                    daemon=True,
                ).start()
                _embedded_worker_started = True
    yield


app = FastAPI(
    title="Grain Storm API",
    version="0.1.0",
    description=(
        "Early-stage crop sequence planning API. Water outputs use modeled "
        "weather and user-supplied crop/soil assumptions; they are not farm recommendations."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Era5WeatherRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class WeatherSource(BaseModel):
    provider: Literal["era5", "imerg_era5"]
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class ContextRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    end_date: date
    start_date: date | None = None
    lookback_days: int = Field(default=90, ge=1, le=3660)
    sources: list[Literal["imerg", "era5", "smap", "power"]] = Field(
        default_factory=lambda: ["imerg", "era5", "smap"], min_length=1
    )
    refresh: bool = False
    acquire_satellites: bool = True
    retry_failed: bool = False


def get_context_service() -> ContextService:
    return ContextService()


class PlanRequest(BaseModel):
    title: str = "Crop sequence comparison"
    field: dict[str, Any]
    crop_catalog: dict[str, dict[str, Any]]
    scenarios: list[dict[str, Any]]
    rotation_effect_catalog: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ranking: dict[str, Any] | None = None
    weather: list[dict[str, Any]] | None = None
    weather_source: WeatherSource | None = None
    imerg_rainfall: list[dict[str, Any]] | None = None


class CropTemplateRequest(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=100)
    net_soil_n_change_kg_ha: float | None = Field(default=None, allow_inf_nan=False)
    nitrogen_source: str | None = Field(default=None, min_length=3, max_length=500)
    nitrogen_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_nitrogen_source(self):
        if self.nitrogen_source is not None:
            self.nitrogen_source = self.nitrogen_source.strip()
        if self.net_soil_n_change_kg_ha is not None and not self.nitrogen_source:
            raise ValueError("nitrogen_source is required with net_soil_n_change_kg_ha")
        return self


class CropSuitabilityRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    crop_ids: list[CropId] = Field(
        default_factory=lambda: ["grain_maize", "grain_soybean"], min_length=1, max_length=6
    )

    @model_validator(mode="after")
    def validate_distinct_crops(self):
        if len(self.crop_ids) != len(set(self.crop_ids)):
            raise ValueError("crop_ids must not contain duplicates")
        return self


class CropCalendarRequest(CropSuitabilityRequest):
    target_year: int = Field(ge=1900, le=2200)


class SoilContextRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class UsCropStatisticsRequest(BaseModel):
    state_alpha: str = Field(pattern=r"^[A-Za-z]{2}$")
    year: int = Field(ge=1900, le=2200)
    crop_ids: list[CropId] = Field(
        default_factory=lambda: ["grain_maize", "grain_soybean"], min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_distinct_crops(self):
        if len(self.crop_ids) != len(set(self.crop_ids)):
            raise ValueError("crop_ids must not contain duplicates")
        return self


class GeoJsonPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class RotationAdviceRequest(BaseModel):
    field_polygon: GeoJsonPolygon
    field_name: str = Field(default="Selected field", min_length=1, max_length=200)
    crop_sequence: list[CropId] = Field(min_length=1, max_length=4)
    preferred_start_date: date
    planning_end_date: date
    schedule_mode: Literal["fixed_gap", "next_planting_window"] = "next_planting_window"
    gaps_after_crops_days: list[int] | None = None
    compare_all_orders: bool = True
    field_inputs: dict[str, Any] = Field(default_factory=dict)
    soil_test: dict[str, Any] | None = None
    management: dict[str, Any] | None = None
    irrigation: dict[str, Any] | None = None
    crop_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rotation_effect_catalog: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ranking: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_rotation_request(self):
        if self.planning_end_date < self.preferred_start_date:
            raise ValueError("planning_end_date cannot be before preferred_start_date")
        if self.gaps_after_crops_days is not None:
            if len(self.gaps_after_crops_days) != len(self.crop_sequence) - 1:
                raise ValueError("gaps_after_crops_days needs one value between each pair of crops")
            if any(value < 0 for value in self.gaps_after_crops_days):
                raise ValueError("gaps_after_crops_days cannot contain negative values")
        unknown = set(self.crop_inputs) - set(self.crop_sequence)
        if unknown:
            raise ValueError(f"crop_inputs contains a crop not in crop_sequence: {sorted(unknown)[0]}")
        return self


def _records_with_nulls(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    safe_frame = dataframe.astype(object).where(pd.notna(dataframe), None)
    return safe_frame.to_dict(orient="records")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "grain-storm"}


@app.get('/v1/crops')
def get_crops() -> dict[str, Any]:
    return {
        "profile_version": PROFILE_VERSION,
        "crops": list_profiles(),
        "sources": SOURCES,
        "note": "Reference profiles populate forms; local calendars and sourced nitrogen assumptions override them.",
    }


@app.get('/v1/crops/{crop_id}')
def get_crop(crop_id: str) -> dict[str, Any]:
    try:
        return get_profile(crop_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown crop profile.") from exc


@app.post('/v1/crops/{crop_id}/planner-template')
def get_crop_planner_template(crop_id: str, request: CropTemplateRequest) -> dict[str, Any]:
    try:
        return planner_template(
            crop_id, request.calendar_id,
            nitrogen_value=request.net_soil_n_change_kg_ha,
            nitrogen_source=request.nitrogen_source,
            nitrogen_note=request.nitrogen_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown crop profile.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post('/v1/crop-suitability')
def get_crop_suitability(request: CropSuitabilityRequest) -> dict[str, Any]:
    try:
        return fetch_location_suitability(request.latitude, request.longitude, request.crop_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GaezError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/v1/crop-calendar')
def get_crop_calendar(request: CropCalendarRequest) -> dict[str, Any]:
    try:
        return fetch_location_crop_calendars(
            request.latitude, request.longitude, request.crop_ids, request.target_year)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GaezError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/v1/crop-yield-baseline')
def get_crop_yield_baseline(request: CropSuitabilityRequest) -> dict[str, Any]:
    try:
        return fetch_location_yield_baselines(request.latitude, request.longitude, request.crop_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GaezError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/v1/soil-context')
def get_soil_context(request: SoilContextRequest) -> dict[str, Any]:
    try:
        return fetch_us_soil_context(request.latitude, request.longitude)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SsurgoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/v1/us-crop-statistics')
def get_us_crop_statistics(request: UsCropStatisticsRequest) -> dict[str, Any]:
    try:
        return fetch_us_crop_statistics(request.state_alpha, request.year, request.crop_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/v1/rotation-advice')
def get_rotation_advice(request: RotationAdviceRequest,
                        service: ContextService = Depends(get_context_service)) -> JSONResponse:
    try:
        status_code, payload = build_rotation_advice(request.model_dump(), service)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (GaezError, SsurgoError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse(status_code=status_code, content=payload)


@app.post("/v1/context")
def get_context(request: ContextRequest, service: ContextService = Depends(get_context_service)) -> dict[str, Any]:
    if request.start_date is not None and "lookback_days" in request.model_fields_set:
        raise HTTPException(status_code=422, detail="Provide start_date or lookback_days, not both.")
    try:
        start = request.start_date or request.end_date - timedelta(days=request.lookback_days - 1)
        return service.query(request.latitude, request.longitude, start.isoformat(),
                             request.end_date.isoformat(), request.sources, request.refresh,
                             acquire_satellites=request.acquire_satellites, retry_failed=request.retry_failed)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get('/v1/context/jobs/{job_id}')
def get_context_job(job_id: str, service: ContextService = Depends(get_context_service)) -> dict[str, Any]:
    from grainstorm.satellite_jobs import SatelliteJobs
    try:
        job = SatelliteJobs(service).get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Unknown satellite job.') from exc
    return {k: job[k] for k in ('id', 'source', 'status', 'start_date', 'end_date', 'error', 'updated_at')}


@app.post("/v1/weather/era5")
def get_era5_weather(request: Era5WeatherRequest) -> dict[str, Any]:
    try:
        dataframe, metadata, _raw = fetch_daily_era5_weather(
            request.latitude,
            request.longitude,
            request.start_date,
            request.end_date,
        )
    except (ValueError, Era5Error) as exc:
        status_code = 422 if isinstance(exc, ValueError) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"weather": _records_with_nulls(dataframe), "metadata": metadata}


@app.post("/v1/plans")
def create_plan(request: PlanRequest) -> dict[str, Any]:
    if request.weather is not None and request.weather_source is not None:
        raise HTTPException(
            status_code=422,
            detail="Provide either weather rows or weather_source, not both.",
        )
    weather_rows = request.weather
    weather_metadata: dict[str, Any] | None = None

    if request.weather_source is not None:
        source = request.weather_source
        try:
            if source.provider == "imerg_era5":
                if request.imerg_rainfall is not None:
                    raise ValueError("imerg_era5 already selects rainfall; omit imerg_rainfall.")
                context = get_context_service().query(source.latitude, source.longitude,
                    source.start_date, source.end_date, sources=["imerg", "era5"])
                incomplete = {name: {k: data[k] for k in ("status", "missing_dates", "invalid_dates", "errors", "acquisition_required", "jobs")}
                              for name, data in context["sources"].items() if data["status"] != "complete"}
                if incomplete:
                    pending = any(j['status'] in {'queued', 'running', 'waiting'} for data in incomplete.values() for j in data['jobs'])
                    raise HTTPException(status_code=202 if pending else 422, detail={
                        "message": "Satellite retrieval is queued or processing; retry this plan after jobs complete." if pending else "Complete IMERG rainfall and ERA5 ET0 coverage is required before planning.",
                        "sources": incomplete,
                    })
                weather_rows, weather_metadata = merge_imerg_weather(
                    context["sources"]["imerg"]["records"], context["sources"]["era5"]["records"])
                weather_metadata["et0_source"] = "ERA5 reference evapotranspiration"
                weather_metadata["context"] = {**context, "sources": {
                    name: {k: v for k, v in data.items() if k != "records"}
                    for name, data in context["sources"].items()}}
            else:
                dataframe, weather_metadata, _raw = fetch_daily_era5_weather(
                    source.latitude, source.longitude, source.start_date, source.end_date)
                weather_rows = _records_with_nulls(dataframe)
        except (ValueError, Era5Error) as exc:
            status_code = 422 if isinstance(exc, ValueError) else 502
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    if weather_rows is None:
        raise HTTPException(
            status_code=422,
            detail="Provide weather rows or weather_source (imerg_era5 or era5).",
        )

    if request.imerg_rainfall is not None:
        try:
            weather_rows, merged_metadata = merge_imerg_weather(request.imerg_rainfall, weather_rows)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        merged_metadata["et0_metadata"] = weather_metadata
        if request.weather_source is not None:
            merged_metadata["et0_source"] = "ERA5 reference evapotranspiration"
        weather_metadata = merged_metadata

    payload = request.model_dump(exclude={"weather_source", "imerg_rainfall"})
    payload["weather"] = weather_rows
    try:
        report = simulate_scenarios(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"report": report, "weather_metadata": weather_metadata}
