-- SampleT: samples, with the hashed Primary Key, the website's edits, and
-- Foreign Keys to the effort, the sighting (by Research Group, Vessel, Date
-- and Sighting, SightingID settling a tie), the sighting event (the record
-- SightingEventID names), research group, vessel and species. IndividualID is
-- the Foreign Key to IndividualT, copied from DB167; one that names no
-- individual is left NULL, an orphan.
with {{ replayed('SampleT') }}
select s.id, {{ column_list('SampleT', 's', {'IndividualID': checked_reference('s."IndividualID"', 'IndividualT')}) }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       {{ edited_reference('sighting_id', 'sighting.id', 'SightingT') }} as sighting_id,
       {{ edited_reference('sighting_event_id', legacy_id(ref('keyed_SightingEventT'), 'SightingEventID', 's."SightingEventID"'), 'SightingEventT') }} as sighting_event_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       sp.id::integer as species_id
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join lateral {{ parent_id(ref('keyed_SightingT'), 'SightingID', 's.__sighting', 's."SightingID"') }} sighting on true
{{ species_join('s') }}
{{ group_and_vessel_joins('s') }}
