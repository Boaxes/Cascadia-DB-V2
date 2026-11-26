-- Every field a website edit set holds the edit's value in dbo. Columns the
-- build works out itself (a track's line, status and vessel) are left out:
-- those are worked out again from the edited columns. So is a Foreign Key an
-- edit set to a record that is not there: it is NULL, an orphan
-- (macros/replay.sql, edited_reference).
with records as (
    {%- for table, key in primary_keys().items() %}
    select '{{ table }}' as target_table, "{{ key }}"::text as target_pk, to_jsonb(t) as record
    from {{ ref(table) }} t
    {{ "union all" if not loop.last }}
    {%- endfor %}
)
select e.target_table, e.target_pk, f.key as column_name, f.value as edit, r.record -> f.key as now
from {{ ref('edits') }} e
join records r on r.target_table = e.target_table and r.target_pk = e.target_pk
cross join lateral jsonb_each(e.changes) f
where r.record ? f.key
  and f.key not in ('geom', 'length_nm', 'point_count', 'track_status', 'file_name', 'vessel_id')
  and r.record -> f.key is distinct from f.value
  and not (jsonb_typeof(f.value) = 'string' and r.record ->> f.key = replace(f.value #>> '{}', ' ', 'T'))
  and not (f.key in ('daily_effort_id', 'sighting_id', 'sighting_event_id', 'species_id', 'IndividualID',
                     'ResearchGroupID', 'TrackCompleteCodeID', 'SourceID')
           and r.record -> f.key = 'null'::jsonb)
