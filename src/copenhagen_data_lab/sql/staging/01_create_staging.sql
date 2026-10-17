-- Staging layer: dimensions from StatBank metadata + cleaned, typed observations.
-- Constraints make the documented grain and code integrity enforceable by DuckDB itself:
-- a duplicate key, an unknown code or a negative count aborts the load.

CREATE TABLE dim_area (
    area_code       VARCHAR PRIMARY KEY,
    area_name       VARCHAR NOT NULL,
    area_level      VARCHAR NOT NULL
                    CHECK (area_level IN ('country', 'region', 'municipality', 'special_area')),
    is_focus        BOOLEAN NOT NULL,
    is_primary      BOOLEAN NOT NULL,
    has_age_detail  BOOLEAN NOT NULL,
    metadata_order  INTEGER NOT NULL
);

CREATE TABLE dim_sex (
    sex_code    VARCHAR PRIMARY KEY,
    sex_label   VARCHAR NOT NULL,
    is_total    BOOLEAN NOT NULL,
    sort_order  INTEGER NOT NULL
);

CREATE TABLE dim_marital_status (
    marital_status_code   VARCHAR PRIMARY KEY,
    marital_status_label  VARCHAR NOT NULL,
    is_total              BOOLEAN NOT NULL,
    sort_order            INTEGER NOT NULL
);

CREATE TABLE dim_age (
    age_code         VARCHAR PRIMARY KEY,
    age_label        VARCHAR NOT NULL,
    is_total         BOOLEAN NOT NULL,
    age_years        INTEGER,
    age_group        VARCHAR,
    age_group_order  INTEGER,
    sort_order       INTEGER NOT NULL,
    CHECK (is_total OR (age_years IS NOT NULL AND age_group IS NOT NULL))
);

CREATE TABLE dim_period (
    period_code     VARCHAR PRIMARY KEY,      -- original StatBank identifier, e.g. 2026K3
    period_label    VARCHAR NOT NULL,         -- e.g. 2026Q3
    year            SMALLINT NOT NULL,
    quarter         TINYINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    period_index    INTEGER NOT NULL UNIQUE,  -- year * 4 + quarter - 1; contiguous across years
    reference_date  DATE NOT NULL,            -- population is counted on this day
    is_latest       BOOLEAN NOT NULL
);

-- Grain: one row per (area, sex, age, marital status, quarter).
CREATE TABLE stg_population (
    area_code            VARCHAR NOT NULL REFERENCES dim_area (area_code),
    sex_code             VARCHAR NOT NULL REFERENCES dim_sex (sex_code),
    age_code             VARCHAR NOT NULL REFERENCES dim_age (age_code),
    marital_status_code  VARCHAR NOT NULL REFERENCES dim_marital_status (marital_status_code),
    period_code          VARCHAR NOT NULL REFERENCES dim_period (period_code),
    population           BIGINT CHECK (population >= 0),
    value_status         VARCHAR NOT NULL CHECK (value_status IN ('reported', 'missing')),
    raw_value            VARCHAR NOT NULL,
    source_request       VARCHAR NOT NULL,
    PRIMARY KEY (area_code, sex_code, age_code, marital_status_code, period_code),
    CHECK ((value_status = 'reported') = (population IS NOT NULL))
);
