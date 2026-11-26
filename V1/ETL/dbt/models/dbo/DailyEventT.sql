-- DailyEventT: the day log, with its hashed Primary Key, the website's edits,
-- and its Foreign Keys: the effort (by Research Group, Vessel and Date), the
-- research group, the vessel and the day-log code. geom is its position.
with {{ replayed('DailyEventT') }}
select s.id, {{ column_list('DailyEventT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       ec.id::integer as event_code_id,
       {{ adapter.quote(this.schema) }}.point_from(s."Dec Lat", s."Dec Long") as geom
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join {{ ref('event_code_keys') }} ec on ec.key = {{ build_fn() }}.key_text(s."Code")
{{ group_and_vessel_joins('s') }}
