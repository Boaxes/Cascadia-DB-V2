-- The timeline of day-log entries, sightings and weather on an effort's page.
-- Every research group.
{{ config(materialized='view') }}
select 'event:' || v."DailyEventID" as row_key, v.daily_effort_id, 'event' as kind, v."EventDateTime" as at,
       v."DailyEventID" as legacy_id, st_y(v.geom) as lat, st_x(v.geom) as lon, v.geom,
       coalesce((select c.name || ' (' || c."EventCode" || ')' from {{ ref('EventCodeT') }} c
                 where c."EventCodeID" = v.event_code_id), v."Code", 'log entry') as label
from {{ ref('DailyEventT') }} v
union all
select 'sighting:' || s."SightingID", s.daily_effort_id, 'sighting', s."StartDateTime", s."SightingID",
       st_y(s.geom), st_x(s.geom), s.geom,
       coalesce((select sp."CommonName" from {{ ref('SpeciesT') }} sp where sp."SpeciesID" = s.species_id),
                s."Species", 'sighting')
from {{ ref('SightingT') }} s
union all
select 'condition:' || c."DailyConditionID", c.daily_effort_id, 'condition', c."ConditionDateTime",
       c."DailyConditionID", st_y(c.geom), st_x(c.geom), c.geom,
       'Beaufort ' || coalesce(c."Beaufort"::text, '?')
from {{ ref('DailyConditionT') }} c
