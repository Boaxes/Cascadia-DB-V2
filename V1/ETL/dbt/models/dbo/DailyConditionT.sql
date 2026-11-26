-- DailyConditionT: weather and sea readings, with the hashed Primary Key, the
-- website's edits, and Foreign Keys to the effort, research group and vessel.
-- geom is the position; visibility_nm is Visibility (nm), else Visibility,
-- where it is a plain number.
with {{ replayed('DailyConditionT') }}
select s.id, {{ column_list('DailyConditionT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       {{ adapter.quote(this.schema) }}.point_from(s."Dec Lat", s."Dec Long") as geom,
       (case when btrim(s."Visibility (nm)") ~ '^[0-9]+(\.[0-9]+)?$' then btrim(s."Visibility (nm)")::numeric
             when btrim(s."Visibility") ~ '^[0-9]+(\.[0-9]+)?$' then btrim(s."Visibility")::numeric
        end)::numeric(8,2) as visibility_nm
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
{{ group_and_vessel_joins('s') }}
