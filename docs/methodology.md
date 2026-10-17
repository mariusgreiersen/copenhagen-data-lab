## Methodology

### The source table

All figures come from **FOLK1A — Population at the first day of the quarter by region, sex,
age, marital status and time**, published by Statistics Denmark in StatBank and retrieved
through the official StatBank API (`api.statbank.dk/v1`). The unit is *Number* (persons).
FOLK1A is register-based: it counts residents registered in the Central Person Register on the
first day of each quarter (1 January, 1 April, 1 July, 1 October). It is quarterly and
**not real-time** — the newest quarter is typically published around six weeks after its
reference date.

### What is extracted

Variable codes are never hard-coded. Each run first downloads the table metadata
(`/v1/tableinfo`) and

* resolves area codes from their official labels (e.g. *Copenhagen* → `101`),
* verifies that `TOT`, `IALT` and `TOT` really are the *total* categories for sex, age and
  marital status,
* verifies that every other age code is a single year (so no broad band is summed with single
  years), and
* classifies areas: *All Denmark* (country), the five *Region …* areas, *Christiansø* (an
  area that belongs to no municipality) and the 98 municipalities.

Two bounded cubes are then requested in the semicolon-separated `CSV` format, marital status
fixed at its total:

| Request | Areas | Sex | Age | Purpose |
|---|---|---|---|---|
| `area_totals` | all 105 areas | total, men, women | total | trends, comparisons, geographic checks |
| `focus_age_detail` | All Denmark + 5 focus municipalities | total, men, women | total + 0…125 | age analysis |

`CSV` was chosen over `BULK` deliberately: tested against the live API, `BULK` omits cells
whose value is zero, which would make a genuine zero indistinguishable from a missing
observation. `CSV` returns the complete cube but is capped at 1,000,000 cells per request, so
the extractor halves the period range whenever the API answers `REQUEST-LIMIT`.

**Copenhagen means Copenhagen municipality** (Københavns Kommune, code 101). It is not the
Capital Region (Region Hovedstaden) and not the wider metropolitan area. Frederiksberg is a
separate municipality enclosed by Copenhagen.

### Validation before anything is published

| Check | Rule | On failure |
|---|---|---|
| A — Required columns | Exactly the expected CSV columns | blocks |
| B — Data types | Every value is an integer or a recognised missing marker (`..`, `.`, `-`, `:`, empty) | blocks |
| C — Nonnegative | No negative counts | blocks |
| D — Unique keys | One row per request × area × sex × age × marital status × quarter | blocks |
| D2 — Cross-request consistency | Cells requested twice carry identical values | blocks |
| E — Missing values | Share of missing observations; zeros are counted separately as valid | warns ≤ 1 %, blocks above |
| F — Time continuity | No missing quarters; no newer published quarter left out | warns |
| G — Referential validity | Every code exists in the table metadata | blocks |
| H1–H4 — Aggregate consistency | men + women = total; single ages = age total; 98 municipalities + Christiansø = All Denmark; 5 regions = All Denmark | blocks |
| R0–R3 | non-empty extract, unit is *Number*, valid quarter codes, complete cube | blocks |

After loading, nine more checks (V1–V9) verify row counts, table grains, expected
observations, valid periods, that age groups reconcile to official totals, and that the SQL
year-over-year growth and national shares match an **independent Pandas recomputation**.
A run that fails any blocking check is recorded as failed and the previously published
warehouse and snapshot stay in place.

### Missing and suppressed values

Missing markers are stored as `NULL` with `value_status = 'missing'` and the original marker
in `raw_value`. They are **never replaced with zero** and never interpolated; charts show them
as gaps. The FOLK1A metadata declares `suppressedDataValue = "0"`. FOLK1A is a full register
count without confidentiality suppression, so zeros (e.g. no 120-year-olds in a municipality)
are treated as genuine zero counts — a documented assumption, see *Limitations*.

### Derived indicators (calculated by Copenhagen Data Lab)

These are **not** figures published by Statistics Denmark.

* **Year-over-year growth (%)** = (population ÷ population in the same quarter one year
  earlier − 1) × 100. The comparison quarter is found by an exact join on the quarter index
  (`period_index − 4`), not by `LAG(…, 4)`, which counts rows and would silently compare
  against the wrong quarter if one were missing. No comparable quarter → no value.
* **Population change** = population − population in the same quarter one year earlier
  (persons).
* **Share of Denmark (%)** = area population ÷ *All Denmark* population for the **same
  quarter** × 100.
* **Indexed growth** = population ÷ population in the chosen base quarter × 100.
* **Age groups** (0–17, 18–29, 30–44, 45–64, 65+) are sums of single-year ages. If any single
  year in a band is missing, the band is unavailable rather than understated.
* **Age-group share (%)** = band population ÷ official age total for the same area, quarter
  and sex × 100.
* **Median age** = the first single-year age at which the cumulative count reaches half of
  the population.
* **Ranks** are among the 98 municipalities within the same quarter; All Denmark and
  Christiansø are never ranked.
* A difference between two percentages is expressed in **percentage points (pp)**, not as a
  percent change.

### Time periods

Quarter codes such as `2026K3` are kept as the original identifier and parsed into year,
quarter, a reference date (first day of the quarter) and a contiguous integer `period_index`
(`year × 4 + quarter − 1`). All ordering uses that index — quarter codes are never sorted as
plain text in analytical logic.

### Limitations

* Single-year age detail is extracted only for All Denmark and five focus municipalities, to
  keep the snapshot small; age metrics are unavailable for other municipalities.
* Marital status is extracted only as its total.
* The interpretation of `suppressedDataValue = "0"` as "no suppression in practice" is an
  assumption based on FOLK1A being a full register count.
* Population changes reflect births, deaths, migration and register corrections together; this
  dashboard does not decompose them, and co-movements between areas do not imply causation.
* Statistics Denmark may revise published figures; the dashboard shows the snapshot that was
  downloaded, identified by its checksum and extraction time.
* Data is quarterly; the dashboard is refreshed by a monthly scheduled check and a reviewed pull
  request, so new quarters appear only after that review and redeployment.

### Attribution

Source: Statistics Denmark (StatBank, table FOLK1A). Statistics Denmark permits free reuse of
StatBank data with source attribution, corresponding to CC BY 4.0. Derived indicators are own
calculations based on data from Statistics Denmark.
