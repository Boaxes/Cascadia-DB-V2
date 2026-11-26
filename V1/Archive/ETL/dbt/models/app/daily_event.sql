{{ config(materialized='updatable_view', meta={'check_option': true}) }}
SELECT v."DailyEventID"    AS id,
       v."DailyEventID"    AS legacy_daily_event_id,
       v."Research Group"  AS research_group,
       v."DailyEffortID"   AS daily_effort_id,
       v.vessel_id,
       v."Code"            AS code,
       v."EventDateTime"   AS event_datetime,
       v."Time"            AS event_time,
       ST_Y(v.geom)        AS lat,
       ST_X(v.geom)        AS lon,
       v.geom,
       v."ObsL"            AS observer_left,
       v."ObsR"            AS observer_right,
       v."Rec"             AS recorder,
       v."Comments"        AS comments,
       v.event_code_id
FROM   {{ ref('DailyEventT') }} v
WHERE  v."Research Group" = 'CRC'
