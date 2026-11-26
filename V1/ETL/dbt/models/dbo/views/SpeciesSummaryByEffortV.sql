-- DB167's own view, translated (was ETL/schema/dbo_views.sql).
{{ config(materialized='view') }}
SELECT s."Species", sum(s."Est Size Best") AS "SpeciesCount", e."DailyEffortID"
FROM   {{ ref('SightingT') }} s
JOIN   {{ ref('DailyEffortT') }} e
       ON s."Research Group" = e."Research Group" AND s."Vessel" = e."Vessel"
      AND s."Date" = e."Date"
GROUP BY s."Species", e."DailyEffortID"
