"""Raw-data quality checks (Stage 2).

Each check returns a :class:`CheckResult`. Severity decides the consequence:

* ``critical`` — a failure blocks publication (status ``fail``)
* ``warning`` — a failure is recorded and shown, but data is still published (``warn``)

Checks operate on the raw string records so that nothing has been coerced yet: a value
like ``..`` must be *seen* as a missing-value marker, never silently turned into 0.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from copenhagen_data_lab.config.settings import Settings
from copenhagen_data_lab.pipeline.extract import REQUEST_COLUMN, VALUE_COLUMN, RawExtract
from copenhagen_data_lab.pipeline.periods import find_gaps, is_period_code, parse_period

Severity = Literal["critical", "warning"]
Status = Literal["pass", "warn", "fail"]

# Markers StatBank uses for observations that are not available. They are kept as
# "missing" — never interpreted as zero.
MISSING_MARKERS = frozenset({"..", ".", "-", ":", ""})
INTEGER_PATTERN = r"-?\d+"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    name: str
    stage: str
    severity: Severity
    status: Status
    records_tested: int
    invalid_records: int
    explanation: str
    executed_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def blocking(self) -> bool:
        return self.status == "fail"

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["executed_at_utc"] = self.executed_at_utc.isoformat()
        return payload


def make_result(
    check_id: str,
    name: str,
    *,
    stage: str,
    severity: Severity,
    passed: bool,
    tested: int,
    invalid: int,
    explanation: str,
) -> CheckResult:
    if passed:
        status: Status = "pass"
    else:
        status = "fail" if severity == "critical" else "warn"
    return CheckResult(
        check_id, name, stage, severity, status, int(tested), int(invalid), explanation
    )


@dataclass
class _Ctx:
    extract: RawExtract
    settings: Settings
    frame: pd.DataFrame  # raw records with ascii helper columns

    @property
    def dims(self) -> list[str]:
        return [v.upper() for v in self.settings.dimensions.all()]

    def col(self, variable_id: str) -> str:
        return variable_id.upper()


RAW = "raw"


# --------------------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------------------
def check_non_empty(ctx: _Ctx) -> CheckResult:
    expected = sum(r.cells for r in ctx.extract.requests)
    n = len(ctx.frame)
    return make_result(
        "R0",
        "Meaningful extraction",
        stage=RAW,
        severity="critical",
        passed=n > 0 and expected > 0,
        tested=expected,
        invalid=0 if n else expected,
        explanation=f"{n:,} records returned for {len(ctx.extract.requests)} request(s); "
        f"{expected:,} cells requested.",
    )


def check_required_columns(ctx: _Ctx) -> CheckResult:
    required = [REQUEST_COLUMN, *ctx.extract.csv_columns]
    missing = [c for c in required if c not in ctx.frame.columns]
    unexpected = [c for c in ctx.frame.columns if c not in required]
    return make_result(
        "A",
        "Required columns",
        stage=RAW,
        severity="critical",
        passed=not missing and not unexpected,
        tested=len(required),
        invalid=len(missing) + len(unexpected),
        explanation=(
            f"All {len(required)} expected columns present."
            if not missing and not unexpected
            else f"Schema change — missing: {missing or 'none'}; unexpected: {unexpected or 'none'}."
        ),
    )


def check_unit(ctx: _Ctx) -> CheckResult:
    unit = ctx.extract.table_info.unit
    ok = unit == ctx.settings.expected_unit
    return make_result(
        "R1",
        "Unit recognised",
        stage=RAW,
        severity="critical",
        passed=ok,
        tested=1,
        invalid=0 if ok else 1,
        explanation=f"Table unit is {unit!r} (expected {ctx.settings.expected_unit!r}: persons).",
    )


def check_period_format(ctx: _Ctx) -> CheckResult:
    periods = ctx.frame[ctx.col(ctx.settings.dimensions.period)]
    bad = ~periods.map(is_period_code)
    return make_result(
        "R2",
        "Period identifiers",
        stage=RAW,
        severity="critical",
        passed=not bad.any(),
        tested=len(periods),
        invalid=int(bad.sum()),
        explanation="All period codes match the StatBank quarter format YYYYKq."
        if not bad.any()
        else f"Malformed period codes: {sorted(periods[bad].unique())[:5]}",
    )


def check_numeric_values(ctx: _Ctx) -> CheckResult:  # Check B
    values = ctx.frame[VALUE_COLUMN].str.strip()
    numeric = values.str.fullmatch(INTEGER_PATTERN)
    marker = values.isin(MISSING_MARKERS)
    bad = ~(numeric | marker)
    return make_result(
        "B",
        "Data types",
        stage=RAW,
        severity="critical",
        passed=not bad.any(),
        tested=len(values),
        invalid=int(bad.sum()),
        explanation=(
            f"{int(numeric.sum()):,} integer counts and {int(marker.sum()):,} recognised "
            "missing-value markers; no unparseable values."
            if not bad.any()
            else f"Unparseable values, e.g. {sorted(values[bad].unique())[:5]}"
        ),
    )


def check_nonnegative(ctx: _Ctx) -> CheckResult:  # Check C
    values = ctx.frame[VALUE_COLUMN].str.strip()
    numeric = values[values.str.fullmatch(INTEGER_PATTERN)].astype("int64")
    negative = int((numeric < 0).sum())
    return make_result(
        "C",
        "Nonnegative values",
        stage=RAW,
        severity="critical",
        passed=negative == 0,
        tested=len(numeric),
        invalid=negative,
        explanation="No negative population counts."
        if negative == 0
        else f"{negative} negative population counts (impossible).",
    )


def check_unique_keys(ctx: _Ctx) -> CheckResult:  # Check D
    key = [REQUEST_COLUMN, *ctx.dims]
    dupes = int(ctx.frame.duplicated(key, keep=False).sum())
    return make_result(
        "D",
        "Unique observation keys",
        stage=RAW,
        severity="critical",
        passed=dupes == 0,
        tested=len(ctx.frame),
        invalid=dupes,
        explanation=f"Grain: request × {' × '.join(ctx.dims)}. "
        + ("No duplicates." if dupes == 0 else f"{dupes} rows share a key."),
    )


def check_cross_request_consistency(ctx: _Ctx) -> CheckResult:
    """Cells requested by more than one cube must carry identical values."""
    overlap = ctx.frame[ctx.frame.duplicated(ctx.dims, keep=False)]
    conflicts = overlap.groupby(ctx.dims)[VALUE_COLUMN].nunique()
    n_conflicts = int((conflicts > 1).sum())
    return make_result(
        "D2",
        "Cross-request consistency",
        stage=RAW,
        severity="critical",
        passed=n_conflicts == 0,
        tested=len(conflicts),
        invalid=n_conflicts,
        explanation=f"{len(conflicts):,} cells appear in more than one request; "
        + ("all values agree." if n_conflicts == 0 else f"{n_conflicts} disagree."),
    )


def check_cube_completeness(ctx: _Ctx) -> CheckResult:
    """Every requested cell is returned exactly once (CSV format returns full cubes)."""
    invalid = 0
    details: list[str] = []
    for name in dict.fromkeys(r.name for r in ctx.extract.requests):
        expected = sum(r.cells for r in ctx.extract.requests if r.name == name)
        actual = int((ctx.frame[REQUEST_COLUMN] == name).sum())
        invalid += abs(expected - actual)
        details.append(f"{name}: {actual:,}/{expected:,}")
    return make_result(
        "R3",
        "Cube completeness",
        stage=RAW,
        severity="critical",
        passed=invalid == 0,
        tested=sum(r.cells for r in ctx.extract.requests),
        invalid=invalid,
        explanation="Rows returned vs cells requested — " + "; ".join(details) + ".",
    )


def check_missing_values(ctx: _Ctx) -> CheckResult:  # Check E
    values = ctx.frame[VALUE_COLUMN].str.strip()
    missing = int(values.isin(MISSING_MARKERS).sum())
    zeros = int((values == "0").sum())
    share = missing / len(values) if len(values) else 1.0
    limit = ctx.settings.max_missing_share
    status: Status = "pass" if missing == 0 else ("warn" if share <= limit else "fail")
    return CheckResult(
        "E",
        "Missing values",
        RAW,
        "critical",
        status,
        len(values),
        missing,
        f"{share:.3%} of observations missing (warning up to {limit:.1%}, blocked above). "
        f"{zeros:,} reported zeros are kept as valid zero counts.",
    )


def check_time_continuity(ctx: _Ctx) -> CheckResult:  # Check F
    periods = ctx.extract.selection.period_codes
    gaps = find_gaps(periods)
    published = ctx.extract.table_info.variable(ctx.settings.dimensions.period).codes()
    last_index = parse_period(periods[-1]).index
    unrequested_new = [p for p in published if parse_period(p).index > last_index]
    issues = len(gaps)
    text = f"{len(periods)} quarters {periods[0]}–{periods[-1]}; "
    text += "no gaps." if not gaps else f"missing quarters: {', '.join(gaps)} (not imputed)."
    if unrequested_new and ctx.settings.last_period is None:
        issues += len(unrequested_new)
        text += f" Newer published periods not extracted: {unrequested_new}."
    return make_result(
        "F",
        "Time continuity",
        stage=RAW,
        severity="warning",
        passed=issues == 0,
        tested=len(periods),
        invalid=issues,
        explanation=text,
    )


def check_referential_validity(ctx: _Ctx) -> CheckResult:  # Check G
    info = ctx.extract.table_info
    invalid_mask = pd.Series(False, index=ctx.frame.index)
    unknown: dict[str, list[str]] = {}
    for variable_id in ctx.settings.dimensions.all():
        known = set(info.variable(variable_id).codes())
        column = ctx.frame[variable_id.upper()]
        bad = ~column.isin(known)
        if bad.any():
            unknown[variable_id] = sorted(column[bad].unique())[:5]
        invalid_mask |= bad
    n = int(invalid_mask.sum())
    return make_result(
        "G",
        "Referential validity",
        stage=RAW,
        severity="critical",
        passed=n == 0,
        tested=len(ctx.frame),
        invalid=n,
        explanation="Every area, sex, age, marital-status and period code exists in the "
        "table metadata."
        if n == 0
        else f"Codes absent from metadata: {unknown}",
    )


def _numeric(frame: pd.DataFrame) -> pd.Series:
    values = frame[VALUE_COLUMN].str.strip()
    return pd.to_numeric(values.where(values.str.fullmatch(INTEGER_PATTERN)), errors="coerce")


def _aggregate_check(
    ctx: _Ctx,
    check_id: str,
    name: str,
    variable_id: str,
    total_codes: set[str],
    component_codes: set[str],
    frame: pd.DataFrame,
    explanation: str,
) -> CheckResult:
    col = variable_id.upper()
    group_cols = [c for c in ctx.dims if c != col]
    work = frame[frame[col].isin(total_codes | component_codes)].copy()
    work["value"] = _numeric(work)
    work["missing"] = work["value"].isna()
    work["is_total"] = work[col].isin(total_codes)
    work = work.drop_duplicates([*ctx.dims])

    def agg(part: pd.DataFrame) -> pd.DataFrame:
        # A sum over components is only meaningful when no component is missing.
        out = part.groupby(group_cols).agg(value=("value", "sum"), missing=("missing", "sum"))
        out.loc[out["missing"] > 0, "value"] = float("nan")
        return out[["value"]]

    totals = agg(work[work.is_total])
    components = agg(work[~work.is_total])
    joined = totals.join(components, lsuffix="_total", rsuffix="_sum", how="inner")
    comparable = joined.dropna(subset=["value_total", "value_sum"])
    mismatched = int((comparable.value_total != comparable.value_sum).sum())
    skipped = len(joined) - len(comparable)
    text = f"{explanation} {len(comparable):,} groups compared, {mismatched} mismatched"
    text += f", {skipped} skipped (missing components)." if skipped else "."
    return make_result(
        check_id,
        name,
        stage=RAW,
        severity="critical",
        passed=mismatched == 0 and len(comparable) > 0,
        tested=len(comparable),
        invalid=mismatched,
        explanation=text,
    )


def check_aggregate_sex(ctx: _Ctx) -> CheckResult:  # Check H1
    s, t = ctx.settings.dimensions, ctx.settings.totals
    sexes = set(ctx.extract.table_info.variable(s.sex).codes())
    return _aggregate_check(
        ctx,
        "H1",
        "Aggregate consistency: sex",
        s.sex,
        {t.sex},
        sexes - {t.sex},
        ctx.frame,
        "Men + women equal the official total.",
    )


def check_aggregate_age(ctx: _Ctx) -> CheckResult:  # Check H2
    s, t = ctx.settings.dimensions, ctx.settings.totals
    ages = set(ctx.extract.table_info.variable(s.age).codes())
    detail = ctx.frame[ctx.frame[REQUEST_COLUMN] == "focus_age_detail"]
    return _aggregate_check(
        ctx,
        "H2",
        "Aggregate consistency: age",
        s.age,
        {t.age},
        ages - {t.age},
        detail,
        "Single-year ages sum to the official age total.",
    )


def _geo_check(ctx: _Ctx, check_id: str, name: str, levels: set[str], text: str) -> CheckResult:
    s = ctx.settings.dimensions
    sel = ctx.extract.selection
    components = {c for c, lvl in sel.area_levels.items() if lvl in levels}
    totals_frame = ctx.frame[ctx.frame[REQUEST_COLUMN] == "area_totals"]
    return _aggregate_check(
        ctx, check_id, name, s.area, {sel.country_code}, components, totals_frame, text
    )


def check_aggregate_municipalities(ctx: _Ctx) -> CheckResult:  # Check H3
    return _geo_check(
        ctx,
        "H3",
        "Aggregate consistency: municipalities",
        {"municipality", "special_area"},
        "Municipalities plus Christiansø sum to the All Denmark total.",
    )


def check_aggregate_regions(ctx: _Ctx) -> CheckResult:  # Check H4
    return _geo_check(
        ctx,
        "H4",
        "Aggregate consistency: regions",
        {"region"},
        "The five regions sum to the All Denmark total.",
    )


STRUCTURAL_CHECKS: tuple[Callable[[_Ctx], CheckResult], ...] = (
    check_non_empty,
    check_required_columns,
)
CONTENT_CHECKS: tuple[Callable[[_Ctx], CheckResult], ...] = (
    check_unit,
    check_period_format,
    check_referential_validity,
    check_numeric_values,
    check_nonnegative,
    check_unique_keys,
    check_cross_request_consistency,
    check_cube_completeness,
    check_missing_values,
    check_time_continuity,
    check_aggregate_sex,
    check_aggregate_age,
    check_aggregate_municipalities,
    check_aggregate_regions,
)


def run_raw_checks(extract: RawExtract, settings: Settings) -> list[CheckResult]:
    """Run every raw check. Content checks are skipped if the structure is unusable."""
    frame = extract.records
    ctx = _Ctx(extract=extract, settings=settings, frame=frame)
    results = [check(ctx) for check in STRUCTURAL_CHECKS]
    if any(r.blocking for r in results):
        return results
    return results + [check(ctx) for check in CONTENT_CHECKS]
