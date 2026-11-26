-- OtherSpeciesT: other animals noted with a sighting, with the hashed Primary
-- Key, the website's edits, and Foreign Keys to the effort, the sighting,
-- research group, vessel and species.
with {{ replayed('OtherSpeciesT') }}
select s.id, {{ column_list('OtherSpeciesT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       {{ edited_reference('sighting_id', 'sighting.id', 'SightingT') }} as sighting_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       sp.id::integer as species_id
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join lateral {{ parent_id(ref('keyed_SightingT'), 'SightingID', 's.__sighting') }} sighting on true
{{ species_join('s') }}
{{ group_and_vessel_joins('s') }}
