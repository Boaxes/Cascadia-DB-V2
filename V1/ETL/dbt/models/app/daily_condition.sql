{{ config(materialized='updatable_view', meta={'check_option': true}) }}
SELECT c."DailyConditionID"  AS id,
       c."DailyConditionID"  AS legacy_daily_condition_id,
       c."Research Group"    AS research_group,
       c."DailyEffortID"     AS daily_effort_id,
       c.vessel_id,
       c."ConditionDateTime" AS condition_datetime,
       c."ConditionTime"     AS condition_time,
       ST_Y(c.geom)          AS lat,
       ST_X(c.geom)          AS lon,
       c.geom,
       c."Beaufort"          AS beaufort,
       c."Swell"             AS swell_ft,
       c."% Cloud Cover"     AS cloud_cover_pct,
       c."Precipitation"     AS precipitation,
       c."Quality"           AS quality,
       c.visibility_nm,
       c."Comments"          AS comments
FROM   {{ ref('DailyConditionT') }} c
WHERE  c."Research Group" = 'CRC'
