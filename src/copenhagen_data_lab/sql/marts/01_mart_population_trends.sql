-- mart_population_trends
-- Grain: one row per (area_code, period_code) — every area level, total sex, total age,
--        total marital status.
--
-- Year-over-year comparison uses an EXACT same-quarter join (period_index - 4), not
-- LAG(population, 4). LAG counts rows, not quarters: if a quarter were missing from a
-- series, LAG(…, 4) would silently compare against a period five quarters earlier and
-- report a non-comparable "annual" growth. With the join, a missing comparison quarter
-- yields NULL growth instead. See sql/examples/yoy_lag_vs_exact_join.sql.

CREATE OR REPLACE TABLE mart_population_trends AS
WITH totals AS (
    SELECT
        s.area_code,
        s.period_code,
        p.period_index,
        s.population
    FROM stg_population AS s
    JOIN dim_sex AS x USING (sex_code)
    JOIN dim_age AS a USING (age_code)
    JOIN dim_marital_status AS m USING (marital_status_code)
    JOIN dim_period AS p USING (period_code)
    WHERE x.is_total AND a.is_total AND m.is_total
),
country AS (
    SELECT t.period_code, t.population
    FROM totals AS t
    JOIN dim_area AS d USING (area_code)
    WHERE d.area_level = 'country'
)
SELECT
    cur.area_code,
    d.area_name,
    d.area_level,
    d.is_focus,
    cur.period_code,
    p.period_label,
    p.year,
    p.quarter,
    p.period_index,
    p.reference_date,
    cur.population,
    -- Same quarter, previous year (exact match on the quarter index).
    prev_y.period_code                                    AS yoy_comparison_period_code,
    prev_y.population                                     AS population_year_earlier,
    cur.population - prev_y.population                    AS yoy_change,
    100.0 * (cur.population / prev_y.population::DOUBLE - 1) AS yoy_growth_pct,
    -- Immediately preceding quarter (exact match).
    prev_q.population                                     AS population_previous_quarter,
    cur.population - prev_q.population                    AS qoq_change,
    -- Share of the national total for the same reporting period.
    dk.population                                         AS denmark_population,
    CASE WHEN d.area_level <> 'country'
         THEN 100.0 * cur.population / dk.population::DOUBLE END AS share_of_denmark_pct
FROM totals AS cur
JOIN dim_area AS d USING (area_code)
JOIN dim_period AS p USING (period_code)
LEFT JOIN totals AS prev_y
       ON prev_y.area_code = cur.area_code AND prev_y.period_index = cur.period_index - 4
LEFT JOIN totals AS prev_q
       ON prev_q.area_code = cur.area_code AND prev_q.period_index = cur.period_index - 1
LEFT JOIN country AS dk
       ON dk.period_code = cur.period_code
ORDER BY d.metadata_order, p.period_index;
