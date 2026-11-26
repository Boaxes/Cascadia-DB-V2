-- depends_on: {{ ref('rule_column') }}
-- Every field in which dbo differs from what DB167 said is explained: by a
-- cleaning step that claims the column (app.rule_column), or by an audit log
-- entry that changed that field of that record. Nothing changes silently.
-- The old pipeline's own final check, promote.py --verify.
--
-- Only the columns no cleaning step claims are compared, column by column in
-- their own types, and the audit log is consulted only for the rows that
-- differ.
{%- set tables = ['DailyEffortT', 'SightingT', 'DailyConditionT', 'DailyEventT', 'SampleT', 'TrackT',
                  'EffortCrewT', 'IdentificationT', 'SightingEventT', 'OtherSpeciesT', 'EventCodeT'] %}
{%- set keys = {'DailyEffortT': 'DailyEffortID', 'SightingT': 'SightingID', 'DailyConditionT': 'DailyConditionID',
                'DailyEventT': 'DailyEventID', 'SampleT': 'SampleID', 'TrackT': 'TrackID', 'EffortCrewT': 'EffortCrewID',
                'IdentificationT': 'IdentificationID', 'SightingEventT': 'SightingEventID', 'OtherSpeciesT': 'OtherSpeciesID',
                'EventCodeT': 'EventCodeID'} %}
{%- set claimed = {} %}
{%- if execute %}
    {%- for row in run_query('select target_table, column_name from ' ~ ref('rule_column')).rows %}
        {%- do claimed.setdefault(row[0], []).append(row[1]) %}
    {%- endfor %}
{%- endif %}

{%- for t in tables %}
{%- set compared = [] %}
{%- for c in raw_columns(t) %}{% if c.name not in claimed.get(t, []) %}{% do compared.append(c.name) %}{% endif %}{% endfor %}
{{ 'union all' if not loop.first }}
select '{{ t }}' as table_name, r."{{ keys[t] }}"::text as id, v.column_name
from {{ source('raw', t) }} r
join {{ ref(t) }} d on d."{{ keys[t] }}" = r."{{ keys[t] }}"
cross join lateral (values
    {%- for c in compared %}
    ({{ "'" ~ c ~ "'" }}, r.{{ adapter.quote(c) }} is distinct from d.{{ adapter.quote(c) }}){{ "," if not loop.last }}
    {%- endfor %}
    {%- if not compared %}(null::text, false){% endif %}
) v(column_name, differs)
where v.differs
  and not exists (select 1 from {{ ref('audit_changes') }} a
                  where a.target_table = '{{ t }}' and a.target_pk = r."{{ keys[t] }}"::text
                    and a.changes ? v.column_name)
{%- endfor %}
