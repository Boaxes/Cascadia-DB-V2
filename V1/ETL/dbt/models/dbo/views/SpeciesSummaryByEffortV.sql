-- DB167's SpeciesSummaryByEffortV: how many animals of each species each
-- effort saw, the effort found by the Foreign Key daily_effort_id.
select s."Species", sum(s."Est Size Best") as "SpeciesCount", e."DailyEffortID"
from {{ ref('SightingT') }} s
join {{ ref('DailyEffortT') }} e on e.id = s.daily_effort_id
group by s."Species", e."DailyEffortID"
