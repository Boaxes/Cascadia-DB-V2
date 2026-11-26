-- IdentificationT: individual animals recognised in a sighting's photos, with
-- the hashed Primary Key, the website's edits, and Foreign Keys to the effort,
-- the sighting (SightingID settling a tie), research group, vessel and species.
-- IndividualID is the Foreign Key to IndividualT, copied from DB167; one that
-- names no individual is left NULL, an orphan.
with {{ replayed('IdentificationT') }}
select s.id, {{ column_list('IdentificationT', 's', {'IndividualID': checked_reference('s."IndividualID"', 'IndividualT')}) }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       {{ edited_reference('sighting_id', 'sighting.id', 'SightingT') }} as sighting_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       sp.id::integer as species_id
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join lateral {{ parent_id(ref('keyed_SightingT'), 'SightingID', 's.__sighting', 's."SightingID"') }} sighting on true
{{ species_join('s') }}
{{ group_and_vessel_joins('s') }}
