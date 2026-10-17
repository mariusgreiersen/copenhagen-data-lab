"""Pipeline and dashboard configuration.

Every value can be overridden through ``CDL_*`` environment variables (see ``.env.example``).
Dimension *codes* are deliberately absent: area codes are resolved from the table metadata
at run time using the labels below, and the total codes are verified against metadata
before any data is requested.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PACKAGE_ROOT / "sql"


@dataclass(frozen=True)
class Dimensions:
    """Variable identifiers of FOLK1A as published in its metadata (``/v1/tableinfo``)."""

    area: str = "OMRÅDE"
    sex: str = "KØN"
    age: str = "ALDER"
    marital_status: str = "CIVILSTAND"
    period: str = "Tid"

    def all(self) -> tuple[str, ...]:
        return (self.area, self.sex, self.age, self.marital_status, self.period)


@dataclass(frozen=True)
class TotalCodes:
    """Codes that denote an *aggregate* category. Verified against metadata labels."""

    sex: str = "TOT"
    age: str = "IALT"
    marital_status: str = "TOT"


@dataclass(frozen=True)
class AgeGroup:
    label: str
    min_age: int
    max_age: int | None  # None = open-ended upper bound

    def contains(self, age: int) -> bool:
        return age >= self.min_age and (self.max_age is None or age <= self.max_age)


DEFAULT_AGE_GROUPS: tuple[AgeGroup, ...] = (
    AgeGroup("0–17", 0, 17),
    AgeGroup("18–29", 18, 29),
    AgeGroup("30–44", 30, 44),
    AgeGroup("45–64", 45, 64),
    AgeGroup("65+", 65, None),
)


class Settings(BaseModel):
    """Runtime configuration. Construct with :meth:`from_env` in application code."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    # --- Source -------------------------------------------------------------------------
    provider: str = "Statistics Denmark"
    api_base_url: str = "https://api.statbank.dk/v1"
    table_id: str = "FOLK1A"
    language: str = "en"
    expected_unit: str = "Number"
    statbank_table_url: str = "https://www.statbank.dk/FOLK1A"
    api_docs_url: str = "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api"
    licence_name: str = "Free reuse with source attribution (corresponds to CC BY 4.0)"
    licence_url: str = "https://www.dst.dk/en/presse/kildeangivelse"

    # --- HTTP behaviour -----------------------------------------------------------------
    request_timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=4, ge=0, le=8)
    backoff_base_s: float = Field(default=1.0, ge=0)
    backoff_max_s: float = Field(default=20.0, ge=0)
    # The CSV format is limited to 1,000,000 cells per request; stay safely below it.
    max_cells_per_request: int = Field(default=900_000, gt=0, le=1_000_000)

    # --- Scope --------------------------------------------------------------------------
    dimensions: Dimensions = Field(default_factory=Dimensions)
    totals: TotalCodes = Field(default_factory=TotalCodes)
    country_label: str = "All Denmark"
    # Areas with single-year age detail. Labels are resolved to codes via metadata.
    focus_area_labels: tuple[str, ...] = (
        "Copenhagen",
        "Aarhus",
        "Odense",
        "Aalborg",
        "Frederiksberg",
    )
    primary_area_label: str = "Copenhagen"
    # Areas in OMRÅDE that are neither regions nor municipalities.
    special_area_labels: tuple[str, ...] = ("Christiansø",)
    region_label_prefix: str = "Region "
    first_period: str | None = None
    last_period: str | None = None
    age_groups: tuple[AgeGroup, ...] = DEFAULT_AGE_GROUPS

    # --- Quality thresholds -------------------------------------------------------------
    # Share of missing observations above which publication is blocked.
    max_missing_share: float = Field(default=0.01, ge=0, le=1)

    # --- Paths --------------------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"

    @field_validator("first_period", "last_period")
    @classmethod
    def _period_code(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        from copenhagen_data_lab.pipeline.periods import parse_period

        parse_period(value)  # raises on malformed codes
        return value

    @model_validator(mode="after")
    def _primary_is_focus(self) -> Settings:
        if self.primary_area_label not in self.focus_area_labels:
            raise ValueError("primary_area_label must be one of focus_area_labels")
        return self

    # Derived paths -----------------------------------------------------------------------
    @property
    def snapshot_dir(self) -> Path:
        """The published, committed snapshot that the dashboard and CI build from."""
        return self.data_dir / "snapshot"

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse" / "copenhagen_data_lab.duckdb"

    @property
    def build_dir(self) -> Path:
        return self.data_dir / "build"

    @property
    def raw_archive_dir(self) -> Path:
        """Verbatim API responses, one folder per run (local only, not committed)."""
        return self.data_dir / "raw"

    @property
    def run_log_path(self) -> Path:
        return self.data_dir / "runs" / "pipeline_runs.jsonl"

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        env = os.environ
        values: dict[str, object] = {}
        mapping = {
            "CDL_DATA_DIR": ("data_dir", Path),
            "CDL_API_BASE_URL": ("api_base_url", str),
            "CDL_REQUEST_TIMEOUT_S": ("request_timeout_s", float),
            "CDL_MAX_RETRIES": ("max_retries", int),
            "CDL_FIRST_PERIOD": ("first_period", str),
            "CDL_LAST_PERIOD": ("last_period", str),
        }
        for var, (name, cast) in mapping.items():
            if env.get(var):
                values[name] = cast(env[var])
        values.update(overrides)
        return cls(**values)


@dataclass
class _Cache:
    settings: Settings | None = field(default=None)


_cache = _Cache()


def get_settings() -> Settings:
    if _cache.settings is None:
        _cache.settings = Settings.from_env()
    return _cache.settings
