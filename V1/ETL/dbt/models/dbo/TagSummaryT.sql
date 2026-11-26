-- TagSummaryT: tags attached to animals, with the website's edits and Foreign
-- Keys to the effort, the sighting, research group and vessel. Its Primary Key
-- is DB167's TagSummaryID, which has never changed.
with {{ cleaned_ctes('TagSummaryT') }},
r as (
    {{ replay_rows('c', 'TagSummaryT', 'TagSummaryID') }}
),
s as (
    select {{ replayed_columns('TagSummaryT', 'r') }}, r.__edits,
           {{ key_hash('TagSummaryT', ['Research Group', 'Vessel', 'Date'], 'r') }} as __effort,
           {{ key_hash('TagSummaryT', ['Research Group', 'Vessel', 'Date', 'Sighting'], 'r') }} as __sighting
    from r
)
select {{ column_list('TagSummaryT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       {{ edited_reference('sighting_id', 'sighting.id', 'SightingT') }} as sighting_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join lateral {{ parent_id(ref('keyed_SightingT'), 'SightingID', 's.__sighting') }} sighting on true
{{ group_and_vessel_joins('s') }}
