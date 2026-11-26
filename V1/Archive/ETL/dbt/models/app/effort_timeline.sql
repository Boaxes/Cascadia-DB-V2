-- The one read-only view. A UNION, so Postgres cannot update it, which is
-- correct: it is three tables shown as one sequence of what happened that day.
--
-- row_key is synthetic because the three branches share no key space -- V1 used
-- a plain row_id and Django treated it as a primary key, which it was not.
{{ config(materialized='updatable_view') }}
SELECT 'event:' || v."DailyEventID"   AS row_key,
       v."DailyEffortID"              AS daily_effort_id,
       'event'                        AS kind,
       v."EventDateTime"              AS at,
       v."DailyEventID"               AS legacy_id,
       ST_Y(v.geom) AS lat, ST_X(v.geom) AS lon, v.geom,
       -- "Begin (B)": what the code means, with the code itself.
       COALESCE((SELECT c.name || ' (' || c."EventCode" || ')'
                 FROM {{ ref('EventCodeT') }} c WHERE c."EventCodeID" = v.event_code_id),
                v."Code", 'log entry') AS label
FROM   {{ ref('DailyEventT') }} v WHERE v."Research Group" = 'CRC'
UNION ALL
SELECT 'sighting:' || s."SightingID",
       s."DailyEffortID", 'sighting', s."StartDateTime", s."SightingID",
       ST_Y(s.geom), ST_X(s.geom), s.geom,
       COALESCE((SELECT sp.common_name FROM {{ ref('SpeciesT') }} sp
                 WHERE sp.species_id = s.species_id), s."Species", 'sighting')
FROM   {{ ref('SightingT') }} s WHERE s."Research Group" = 'CRC'
UNION ALL
SELECT 'condition:' || c."DailyConditionID",
       c."DailyEffortID", 'condition', c."ConditionDateTime", c."DailyConditionID",
       ST_Y(c.geom), ST_X(c.geom), c.geom,
       'Beaufort ' || COALESCE(c."Beaufort"::text, '?')
FROM   {{ ref('DailyConditionT') }} c WHERE c."Research Group" = 'CRC'
