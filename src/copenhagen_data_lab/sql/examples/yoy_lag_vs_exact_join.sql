-- Year-over-year growth: why LAG(population, 4) is not automatically correct.
--
-- LAG(…, 4) returns the value four ROWS earlier in the window. That equals "the same
-- quarter one year earlier" only if the series has no gaps. To demonstrate, this query
-- removes one quarter (2020K2) from Copenhagen's series and computes YoY growth three ways:
--
--   naive_lag_growth_pct    LAG(…, 4) without a guard  -> wrong right after the gap
--   guarded_lag_growth_pct  LAG(…, 4) but only if the lagged row is exactly 4 quarters back
--   exact_join_growth_pct   self-join on period_index - 4 (the method used by the marts)
--
-- Run it against the published warehouse:
--   duckdb -readonly data/warehouse/copenhagen_data_lab.duckdb < src/copenhagen_data_lab/sql/examples/yoy_lag_vs_exact_join.sql

WITH series AS (
    SELECT area_code, period_code, period_index, population
    FROM mart_population_trends
    WHERE area_code = (SELECT area_code FROM dim_area WHERE is_primary)
      AND period_code <> '2020K2'                       -- simulated missing quarter
),
lagged AS (
    SELECT
        *,
        LAG(population, 4)   OVER w AS lag4_population,
        LAG(period_index, 4) OVER w AS lag4_period_index
    FROM series
    WINDOW w AS (PARTITION BY area_code ORDER BY period_index)
)
SELECT
    cur.period_code,
    cur.population,
    ROUND(100.0 * (cur.population / cur.lag4_population::DOUBLE - 1), 3) AS naive_lag_growth_pct,
    ROUND(CASE WHEN cur.lag4_period_index = cur.period_index - 4
               THEN 100.0 * (cur.population / cur.lag4_population::DOUBLE - 1) END, 3)
                                                                      AS guarded_lag_growth_pct,
    ROUND(100.0 * (cur.population / prev.population::DOUBLE - 1), 3)   AS exact_join_growth_pct
FROM lagged AS cur
LEFT JOIN series AS prev
       ON prev.area_code = cur.area_code AND prev.period_index = cur.period_index - 4
WHERE cur.period_index BETWEEN 2020 * 4 AND 2021 * 4 + 3       -- 2020K1 … 2021K4
ORDER BY cur.period_index;
