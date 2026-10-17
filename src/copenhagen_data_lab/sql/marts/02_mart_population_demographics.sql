-- mart_population_demographics
-- Grain: one row per (area_code, period_code, sex_code, age_group) for areas with
--        single-year age detail (Denmark + focus municipalities).
--
-- Age groups are built ONLY from single-year age codes (dim_age.is_total = false), so the
-- official "Age, total" row is never added to its own components. A group's population is
-- NULL if any of its single-year cells is missing — a partial sum would understate it.
-- Shares use the official age total for the same area/period/sex as denominator; quality
-- check H2 verifies that the single years sum exactly to that total.

CREATE OR REPLACE TABLE mart_population_demographics AS
WITH singles AS (
    SELECT
        s.area_code,
        s.period_code,
        s.sex_code,
        a.age_group,
        a.age_group_order,
        a.age_years,
        s.population
    FROM stg_population AS s
    JOIN dim_age AS a USING (age_code)
    JOIN dim_marital_status AS m USING (marital_status_code)
    JOIN dim_area AS d USING (area_code)
    WHERE NOT a.is_total AND m.is_total AND d.has_age_detail
),
grouped AS (
    SELECT
        area_code,
        period_code,
        sex_code,
        age_group,
        age_group_order,
        MIN(age_years)                                             AS min_age,
        MAX(age_years)                                             AS max_age,
        COUNT(*)                                                   AS single_year_cells,
        COUNT(*) - COUNT(population)                               AS missing_cells,
        CASE WHEN COUNT(population) = COUNT(*) THEN SUM(population)::BIGINT END AS population
    FROM singles
    GROUP BY ALL
),
official_totals AS (
    SELECT s.area_code, s.period_code, s.sex_code, s.population AS age_total_population
    FROM stg_population AS s
    JOIN dim_age AS a USING (age_code)
    JOIN dim_marital_status AS m USING (marital_status_code)
    WHERE a.is_total AND m.is_total
)
SELECT
    g.area_code,
    d.area_name,
    d.area_level,
    g.period_code,
    p.period_label,
    p.period_index,
    g.sex_code,
    x.sex_label,
    g.age_group,
    g.age_group_order,
    g.min_age,
    g.max_age,
    g.population,
    t.age_total_population,
    100.0 * g.population / t.age_total_population::DOUBLE AS share_pct,
    g.single_year_cells,
    g.missing_cells
FROM grouped AS g
JOIN dim_area AS d USING (area_code)
JOIN dim_period AS p USING (period_code)
JOIN dim_sex AS x USING (sex_code)
LEFT JOIN official_totals AS t USING (area_code, period_code, sex_code)
ORDER BY d.metadata_order, p.period_index, x.sort_order, g.age_group_order;
