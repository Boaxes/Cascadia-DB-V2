-- The vessel filter and names: every vessel any effort or sighting uses, one
-- row per vessel.
select vessel_id as id, legacy_vessel_id, code, coalesce(name, code) as name
from {{ ref('VesselListT') }} v
where exists (select 1 from {{ ref('DailyEffortT') }} e where e.vessel_id = v.vessel_id)
   or exists (select 1 from {{ ref('SightingT') }} s where s.vessel_id = v.vessel_id)
