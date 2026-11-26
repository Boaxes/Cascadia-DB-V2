-- ResearchGroupT: DB167's research groups, plus every group the data uses that
-- it lacks. It has not been kept up since 2021. A group is missing when no row
-- has its code, ignoring case and spaces; it is added with its code only (as
-- dbo spells it) and a ResearchGroupID above the highest, in code order.
with {{ cleaned_ctes('ResearchGroupT') }},
used as (
    select coalesce(m.to_value, v.value) as spelling, sum(v.records) as records
    from {{ ref('spelling_values') }} v
    left join {{ ref('spelling_map') }} m on m.unit = v.unit and m.from_value = v.value
    where v.unit = 'research_group'
    group by 1
),
missing as (
    select distinct on ({{ build_fn() }}.key_text(spelling)) btrim(spelling) as code
    from used
    where {{ build_fn() }}.key_text(spelling) is not null
      and {{ build_fn() }}.key_text(spelling) not in
          (select {{ build_fn() }}.key_text("Code") from c where "Code" is not null)
    order by {{ build_fn() }}.key_text(spelling), records desc, spelling collate "C"
)
select {{ column_list('ResearchGroupT', 'c') }}
from c
union all
select ((select max("ResearchGroupID") from c) + row_number() over (order by code collate "C"))::integer,
       code, null::text
from missing
