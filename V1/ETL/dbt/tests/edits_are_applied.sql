-- Every edit in the audit log is what dbo holds: for each record and field, the
-- newest value an edit set is the value in the table. The replay's own check.
-- Left out: the track geometry columns, which come from raw.track_geometry;
-- a track's status, worked out from its link and its file; and vessel_id,
-- which is read through the vessel lookup (models/dbo/lookups).
{% set tables = ['SightingT', 'DailyEffortT', 'DailyConditionT', 'DailyEventT', 'SampleT', 'TrackT'] %}
{% set keys = {'SightingT': 'SightingID', 'DailyEffortT': 'DailyEffortID', 'DailyConditionT': 'DailyConditionID',
               'DailyEventT': 'DailyEventID', 'SampleT': 'SampleID', 'TrackT': 'TrackID'} %}
{%- for t in tables %}
{{ 'union all' if not loop.first }}
select '{{ t }}' as table_name, c.target_pk, f.key as column_name, f.value #>> '{}' as edited, d.value #>> '{}' as stored
from {{ ref('audit_changes') }} c
cross join lateral jsonb_each(c.changes) f
join {{ ref(t) }} x on x."{{ keys[t] }}"::text = c.target_pk
cross join lateral (select to_jsonb(x) -> f.key as value) d
where c.target_table = '{{ t }}'
  and f.key not in ('geom', 'length_nm', 'point_count', 'track_status', 'vessel_id')
  and (f.value #>> '{}') is distinct from (d.value #>> '{}')
  -- The same value written two ways: a number as 1.5 or 1.50, a time with a
  -- space (as the audit log stores it) or a T (as JSON writes it).
  and not (jsonb_typeof(f.value) = 'number' and jsonb_typeof(d.value) = 'number'
           and (f.value #>> '{}')::numeric = (d.value #>> '{}')::numeric)
  and not ((f.value #>> '{}') ~ '^\d{4}-\d\d-\d\d \d\d:\d\d'
           and replace(d.value #>> '{}', 'T', ' ') = (f.value #>> '{}'))
{%- endfor %}
