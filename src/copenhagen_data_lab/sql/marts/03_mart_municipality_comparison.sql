-- mart_municipality_comparison
-- Grain: one row per (area_code, period_code) for municipalities and the country.
--
-- Ranks are computed among municipalities only (98 in FOLK1A), within the same reporting
-- period, so the national total and the non-municipal area Christiansø never take a rank.
-- Rows without a valid year-earlier comparison get a NULL growth rank, not a guessed one.

CREATE OR REPLACE TABLE mart_municipality_comparison AS
WITH base AS (
    SELECT *
    FROM mart_population_trends
    WHERE area_level IN ('municipality', 'country')
),
ranked AS (
    SELECT
        area_code,
        period_code,
        RANK() OVER (PARTITION BY period_code ORDER BY population DESC)      AS rank_population,
        CASE WHEN yoy_growth_pct IS NOT NULL THEN
            RANK() OVER (PARTITION BY period_code, yoy_growth_pct IS NULL
                         ORDER BY yoy_growth_pct DESC) END                  AS rank_yoy_growth,
        COUNT(*) OVER (PARTITION BY period_code)                             AS municipality_count
    FROM base
    WHERE area_level = 'municipality' AND population IS NOT NULL
)
SELECT
    b.area_code,
    b.area_name,
    b.area_level,
    b.is_focus,
    b.period_code,
    b.period_label,
    b.period_index,
    b.reference_date,
    b.population,
    b.yoy_comparison_period_code,
    b.population_year_earlier,
    b.yoy_change,
    b.yoy_growth_pct,
    b.share_of_denmark_pct,
    r.rank_population,
    r.rank_yoy_growth,
    r.municipality_count
FROM base AS b
LEFT JOIN ranked AS r USING (area_code, period_code)
ORDER BY b.period_index, b.area_level, b.population DESC;
