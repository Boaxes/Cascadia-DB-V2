-- Every record that types a vessel or a research group has its Foreign Key
-- to VesselListT and ResearchGroupT (rule 4).
{%- set tables = (hashed_tables() | list) + ['TagSummaryT'] %}
{%- for t in tables %}
select '{{ t }}' as table_name, "Vessel" as vessel, "Research Group" as research_group
from {{ ref(t) }}
where ("Vessel" is not null and vessel_id is null) or ("Research Group" is not null and research_group_id is null)
{{ "union all" if not loop.last }}
{%- endfor %}
