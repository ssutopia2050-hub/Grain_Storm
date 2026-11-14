// Grain Storm v1 frontend types. Keep aligned with frontend_api_contract.md.

export type ISODate = string;
export type SourceName = "imerg" | "smap" | "era5" | "power";
export type SourceStatus =
  | "complete"
  | "partial"
  | "acquisition_pending"
  | "acquisition_required"
  | "upstream_error";
export type JobStatus =
  | "queued"
  | "running"
  | "waiting"
  | "complete"
  | "partial"
  | "auth_required"
  | "failed";

export interface Point {
  latitude: number;
  longitude: number;
}

export type CropProfileId = "grain_maize" | "grain_soybean";

export interface CropProfileSummary {
  id: CropProfileId;
  profile_version: "fao-reference-v1";
  display_name: string;
  scientific_name: string;
  production_form: string;
  aliases: string[];
  indicative_duration_days: { minimum: number; maximum: number };
  calendar_ids: string[];
  nitrogen_status: "local_input_required";
}

export interface CropListResponse {
  profile_version: "fao-reference-v1";
  crops: CropProfileSummary[];
  sources: Record<string, { title: string; url: string; supports: string[] }>;
  note: string;
}

export interface ReferenceCalendar {
  id: string;
  duration_days: number;
  stage_days: [number, number, number, number];
  label: string;
  source_id: string;
  local_override_required: true;
}

export interface CropProfile {
  id: CropProfileId;
  profile_version: "fao-reference-v1";
  display_name: string;
  scientific_name: string;
  production_form: string;
  aliases: string[];
  scope: string;
  gaez: {
    crop_code: "mze" | "soy";
    location_suitability_status: "not_evaluated";
    note: string;
  };
  growing_period: {
    indicative_days: { minimum: number; maximum: number };
    stage_order: ["initial", "development", "mid_season", "late_season"];
    reference_calendars: ReferenceCalendar[];
    local_inputs_needed: string[];
  };
  water: {
    method: string;
    stage_kc: [number, number, number, number];
    stage_kc_units: "dimensionless";
    et0_units: "mm/day";
    output_units: "mm/day";
    indicative_seasonal_need_mm: { minimum: number; maximum: number };
    drought_sensitivity: string;
    source_ids: string[];
    limitations: string[];
  };
  rooting: {
    reference_depth_m: number;
    source_id: "fao_rooting_depth";
    local_override_required: true;
    note: string;
  };
  nitrogen: {
    default_net_soil_n_change_kg_ha: null;
    required_planner_field: "net_soil_n_change_kg_ha";
    status: "local_input_required";
    reason: string;
    soybean_warning: string | null;
  };
  source_ids: string[];
  sources: Record<string, { title: string; url: string; supports: string[] }>;
}

export interface CropTemplateRequest {
  calendar_id: string;
  net_soil_n_change_kg_ha?: number;
  nitrogen_source?: string;
  nitrogen_note?: string;
}

export interface CropTemplateResponse {
  crop_id: CropProfileId;
  calendar_id: string;
  ready_for_planner: boolean;
  missing_inputs: string[];
  planner_crop: Omit<CropInput, "net_soil_n_change_kg_ha"> & {
    net_soil_n_change_kg_ha: number | null;
  };
  warnings: string[];
  sources: CropProfile["sources"];
}

export interface CropSuitabilityRequest extends Point {
  crop_ids?: CropProfileId[];
}

export interface CropSuitabilityResult {
  crop_id: CropProfileId;
  gaez_crop: string;
  gaez_crop_code: "mze" | "soy";
  status: "complete";
  suitability_index_raw: number;
  suitability_index_percent: number;
  suitability_class: {
    code: "VS" | "S" | "MS" | "mS" | "vmS" | "NS";
    label: string;
    attainable_yield_band: string;
  };
  sampled_location: Point;
  raster: {
    objectid: number;
    file_id: string;
    name: string;
    variable: string;
    year: string;
    model: string;
    rcp: string;
    water_supply: string;
    input_level: string;
    c02_fertilization: string;
    units: string;
    download_url: string;
  };
}

export interface CropSuitabilityResponse {
  requested_point: Point;
  dataset: {
    provider: "FAO/IIASA";
    product: string;
    service: string;
    documentation: string;
    attribution: string;
    spatial_resolution: string;
    index_scale: string;
    baseline: {
      time_period: "1981-2010";
      climate_model: "CRUTS32";
      scenario: "Historical";
      water_supply: "Rainfed";
      input_level: "High";
      land_basis: "all land in grid cell";
    };
  };
  crops: CropSuitabilityResult[];
  interpretation: string;
}

export interface CropCalendarRequest extends Point {
  target_year: number;
  crop_ids?: CropProfileId[];
}

export interface CropCalendarResponse {
  requested_point: Point;
  target_year: number;
  dataset: Record<string, string>;
  crops: Array<{
    crop_id: CropProfileId;
    gaez_crop: string;
    cycle_start_day_of_year: number;
    cycle_length_days: number;
    planting_date_for_target_year: ISODate;
    projected_harvest_date: ISODate;
    reference_root_depth_m: number;
    root_depth_source: string;
    planner_overrides: {duration_days: number; root_depth_m: number};
    rasters: Record<string, Record<string, unknown>>;
  }>;
  limitations: string[];
}

export interface CropYieldBaselineResponse {
  requested_point: Point;
  dataset: Record<string, unknown>;
  crops: Array<{
    crop_id: CropProfileId;
    historical_yield_t_ha: number;
    economics_yield_input: {expected_yield_t_ha: number};
    raster: Record<string, unknown>;
  }>;
  limitations: string[];
}

export interface ContextRequest extends Point {
  end_date: ISODate;
  start_date?: ISODate;
  lookback_days?: number;
  sources?: SourceName[];
  refresh?: boolean;
  acquire_satellites?: boolean;
  retry_failed?: boolean;
}

export interface JobSummary {
  id: string;
  source: "imerg" | "smap";
  status: JobStatus;
  start_date: ISODate;
  end_date: ISODate;
  error: string | null;
}

export interface JobDetail extends JobSummary {
  updated_at: number; // Unix epoch seconds
}

export interface ImergRecord {
  date: ISODate;
  gpm_precipitation_mm_day: number | null;
  gpm_random_error_mm_day?: number | null;
  gpm_valid_half_hourly_count?: number | null;
  gpm_wet_half_hourly_count?: number | null;
}

export interface SmapRecord {
  date: ISODate;
  soil_moisture_rootzone_m3_m3: number | null;
  soil_moisture_surface_m3_m3: number | null;
  // Older imported rows can contain numeric strings.
  rootzone_observations?: number | string;
  surface_observations?: number | string;
}

export interface Era5Record {
  date: ISODate;
  rain_mm: number | null;
  et0_mm: number | null;
  hours_recorded?: number;
}

export interface PowerRecord {
  date: ISODate;
  T2M: number | null;
  PRECTOTCORR: number | null;
  RH2M: number | null;
}

export type SourceRecord = ImergRecord | SmapRecord | Era5Record | PowerRecord;

export interface SourceContext<T extends SourceRecord = SourceRecord> {
  status: SourceStatus;
  product: string;
  location_key: string;
  location_matching: "native_grid_cell" | "requested_point";
  units: Record<string, string>;
  records: T[];
  missing_dates: ISODate[];
  invalid_dates: ISODate[];
  cache_hits: number;
  fetched_days: number;
  provenance: unknown[];
  errors: string[];
  jobs: JobSummary[];
  acquisition_required: boolean;
  note: string;
}

export interface ContextResponse {
  requested_point: Point;
  start_date: ISODate;
  end_date: ISODate;
  time_support: "UTC calendar days";
  sources: Partial<{
    imerg: SourceContext<ImergRecord>;
    smap: SourceContext<SmapRecord>;
    era5: SourceContext<Era5Record>;
    power: SourceContext<PowerRecord>;
  }>;
}

export interface FieldInput {
  name?: string;
  area_ha: number;
  soil_water_capacity_mm: number;
  initial_soil_water_mm: number;
  initial_mineral_n_kg_ha: number;
  initial_available_p_kg_ha?: number;
  initial_exchangeable_k_kg_ha?: number;
  initial_organic_matter_percent?: number;
  initial_soil_ph?: number;
  soil_water_capacity_depth_m?: number;
  fallow_kc?: number;
  irrigation_enabled?: boolean;
  irrigation_trigger_fraction?: number;
}

export interface CropInput {
  duration_days: number;
  net_soil_n_change_kg_ha?: number;
  stage_kc?: [number, number, number, number];
  stage_days?: [number, number, number, number];
  water_need_mm?: number;
  profile_id?: CropProfileId;
  profile_version?: string;
  calendar_id?: string;
  water_profile_source_id?: string;
  nitrogen_assumption_source?: string;
  nitrogen_assumption_note?: string;
  planting_windows?: Array<{
    label: string;
    start_month_day: string; // MM-DD
    end_month_day: string; // MM-DD; may wrap across New Year
  }>;
  root_depth_m?: number;
  nutrient_budget?: Partial<Record<"n" | "p" | "k", {
    fertilizer?: number;
    residue_release?: number;
    crop_uptake_from_soil?: number;
    other_losses?: number;
    biological_fixation?: number; // N only; reported, not credited to soil N
    source: string;
    note?: string;
  }>>;
  soil_effects?: {
    organic_matter_change_percentage_points?: number;
    ph_change?: number;
    source: string;
    note?: string;
  };
  economics?: {
    expected_yield_t_ha: number;
    price_per_tonne: number;
    variable_cost_per_ha: number;
    currency: string;
    source: string;
  };
}

export interface ScenarioInput {
  name: string;
  start_date: ISODate;
  planning_end_date?: ISODate;
  schedule_mode?: "fixed_gap" | "next_planting_window";
  crops: string[];
  gaps_after_crops_days?: number[];
}

export interface PlanRequest {
  title?: string;
  field: FieldInput;
  crop_catalog: Record<string, CropInput>;
  scenarios: ScenarioInput[];
  rotation_effect_catalog?: Record<string, {
    pest_disease_break_score: number; // -2..2
    source: string;
    note?: string;
  }>;
  ranking?: {
    enabled: boolean;
    weights: Partial<Record<
      "net_margin" | "irrigation" | "unmet_water" | "nutrient_shortfall" | "pest_disease",
      number
    >>;
  };
  weather_source: {
    provider: "imerg_era5" | "era5";
    latitude: number;
    longitude: number;
    start_date: ISODate;
    end_date: ISODate;
  };
}

export interface CropResult {
  crop: string;
  earliest_planting_date: ISODate;
  planting_date: ISODate;
  planned_harvest_date: ISODate;
  gap_before_days: number;
  calendar_wait_before_days: number;
  planting_window_status:
    | "not_provided"
    | "within_window"
    | "outside_window"
    | "shifted_to_window";
  matched_planting_window: {
    label: string;
    start_date: ISODate;
    end_date: ISODate;
  } | null;
  duration_days: number;
  rain_mm: number;
  irrigation_mm: number;
  crop_water_need_mm: number;
  root_depth_m: number | null;
  effective_root_zone_capacity_mm: number;
  irrigation_m3_for_field: number;
  unmet_water_mm: number;
  soil_water_start_mm: number;
  soil_water_end_mm: number;
  profile_equivalent_soil_water_end_mm: number;
  mineral_n_start_kg_ha: number;
  net_soil_n_change_kg_ha: number;
  estimated_mineral_n_end_kg_ha: number;
  estimated_n_shortfall_kg_ha: number;
  mineral_n_start_kg_for_field: number;
  net_soil_n_change_kg_for_field: number;
  estimated_mineral_n_end_kg_for_field: number;
  estimated_n_shortfall_kg_for_field: number;
  available_p_start_kg_ha: number | null;
  net_available_p_change_kg_ha: number | null;
  estimated_available_p_end_kg_ha: number | null;
  estimated_p_shortfall_kg_ha: number | null;
  exchangeable_k_start_kg_ha: number | null;
  net_exchangeable_k_change_kg_ha: number | null;
  estimated_exchangeable_k_end_kg_ha: number | null;
  estimated_k_shortfall_kg_ha: number | null;
  nutrient_budget: Record<"n" | "p" | "k", Record<string, unknown> | null>;
  soil_effects: Record<string, unknown> | null;
  economics: Record<string, unknown> | null;
  input_provenance: Partial<{
    profile_id: CropProfileId;
    profile_version: string;
    calendar_id: string;
    water_profile_source_id: string;
    nitrogen_assumption_source: string;
    nitrogen_assumption_note: string;
  }>;
}

export interface IrrigationEvent {
  date: ISODate;
  amount_mm: number;
  amount_m3_for_field: number;
  crop: string;
}

export interface ScenarioResult {
  name: string;
  sequence: CropResult[];
  schedule_mode: "fixed_gap" | "next_planting_window";
  planning_end_date: ISODate | null;
  calendar_status: "feasible" | "infeasible" | "not_fully_evaluated";
  calendar_feasible: boolean | null;
  schedule_issues: Array<Record<string, unknown> & {code: string; message: string}>;
  schedule_warnings: Array<Record<string, unknown> & {code: string; message: string}>;
  rotation_span_days: number;
  total_configured_gap_days: number;
  total_calendar_wait_days: number;
  fallow_periods: Array<Record<string, unknown>>;
  rotation_effects: Array<Record<string, unknown>>;
  pest_disease_rotation_score: number | null;
  total_rain_mm: number;
  total_irrigation_mm: number;
  total_irrigation_m3_for_field: number;
  total_unmet_water_mm: number;
  estimated_final_mineral_n_kg_ha: number;
  estimated_final_mineral_n_kg_for_field: number;
  estimated_final_available_p_kg_ha: number | null;
  estimated_final_exchangeable_k_kg_ha: number | null;
  estimated_final_organic_matter_percent: number | null;
  estimated_final_soil_ph: number | null;
  total_nutrient_shortfall_kg_ha: number;
  estimated_total_margin_for_field: number | null;
  economics_currency: string | null;
  economics_status: "complete" | "not_fully_evaluated";
  irrigation_events: IrrigationEvent[];
}

export interface PlanResponse {
  report: {
    title: string;
    field: {
      name: string;
      area_ha: number;
      initial_soil_water_mm: number;
      soil_water_capacity_mm: number;
      soil_water_capacity_depth_m: number | null;
      initial_mineral_n_kg_ha: number;
      initial_available_p_kg_ha: number | null;
      initial_exchangeable_k_kg_ha: number | null;
      initial_organic_matter_percent: number | null;
      initial_soil_ph: number | null;
      fallow_kc: number | null;
    };
    scenarios: ScenarioResult[];
    comparison: {
      ranking: {
        status: "not_requested" | "insufficient_inputs" | "complete";
        ranked_scenarios: Array<Record<string, unknown>>;
        warning?: string;
      };
    };
    assumptions_and_limits: string[];
  };
  weather_metadata: Record<string, unknown> | null;
}

export interface PlanPendingResponse {
  detail: {
    message: string;
    sources: Partial<Record<SourceName, {
      status: SourceStatus;
      missing_dates: ISODate[];
      invalid_dates: ISODate[];
      errors: string[];
      acquisition_required: boolean;
      jobs: JobSummary[];
    }>>;
  };
}

// @ts-ignore
export const ACTIVE_JOB_STATES = new Set<JobStatus>(["queued", "running", "waiting"]);
export const isSourceProcessing = (source: SourceContext): boolean =>
  source.jobs.some((job) => ACTIVE_JOB_STATES.has(job.status));
