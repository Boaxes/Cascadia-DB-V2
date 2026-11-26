-- SightingEventT: what happened during each sighting, with the hashed Primary
-- Key, the website's edits, and Foreign Keys to the effort and the sighting
-- (by Research Group, Vessel, Date and Sighting), research group and vessel.
with {{ replayed('SightingEventT') }}
select s.id, {{ column_list('SightingEventT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       {{ edited_reference('sighting_id', 'sighting.id', 'SightingT') }} as sighting_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join lateral {{ parent_id(ref('keyed_SightingT'), 'SightingID', 's.__sighting') }} sighting on true
{{ group_and_vessel_joins('s') }}
