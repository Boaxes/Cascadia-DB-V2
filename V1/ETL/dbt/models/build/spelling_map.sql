-- The spelling rule: every value a choice column holds that dbo spells
-- differently, and the spelling it becomes. One row per original spelling.
--
-- Values are grouped by their key: the value trimmed, runs of spaces made one,
-- in lower case (so 'Slow travel' and 'slow travel ' are one group). Groups are
-- then joined by the typo list (seeds/typos.csv: wrong -> correct) and the
-- synonym list (seeds/synonyms.csv). Each joined set becomes one spelling:
--   1. where the column has a category table (species, research group,
--      vessel, day-log code), the category table's spelling;
--   2. otherwise the existing spelling nearest to Title Case
--      (build.title_distance), or for a unit of measure the one with fewest
--      capitals; for a typo only the correct side's spellings count;
--   3. between equally near spellings, the most common, then the first in
--      character order, so the result never depends on row order.
-- DailyEffortT's Sub-area is the exception: a spelling in Doug Sandilands's
-- table (seeds/sub_areas.csv) becomes its corrected sub-area.
--
--   kind  capitals  differs only in capital letters
--         spaces    differs only in spaces
--         typo      a spelling the typo list corrects
--         synonym   a different spelling of the same thing
--         corrected Doug Sandilands's correction
{%- set fn = build_fn() %}
{%- set ws = "E' \\t\\r\\n\\f\\v\\u00a0'" %}

with recursive kinds as (
    select table_name, column_name, coalesce(nullif(vocabulary, ''), table_name || '.' || column_name) as unit
    from {{ ref('column_kinds') }} where kind = 'choice'
),
vals as (
    select unit, value, sum(records)::integer as records from {{ ref('spelling_values') }} group by 1, 2
),
-- Doug Sandilands's sub-areas.
doug as (
    select v.unit, v.value, d."Corrected Sub-Area" as to_value
    from vals v
    join {{ ref('sub_areas') }} d on {{ fn }}.key_text(d."Sub-Area Database Entries") = {{ fn }}.key_text(v.value)
    where v.unit = 'DailyEffortT.Sub-area'
),
general as (
    select v.* from vals v where not exists (select 1 from doug d where d.unit = v.unit and d.value = v.value)
),
keyed as (
    select unit, value, records, {{ spelling_key('unit', 'value') }} as k from general
),
typo_pairs as (
    select k.unit, {{ spelling_key('k.unit', 't.wrong') }} as a, {{ spelling_key('k.unit', 't.correct') }} as b,
           regexp_replace(btrim(t.correct, {{ ws }}), '\s+', ' ', 'g') as correct
    from {{ ref('typos') }} t
    join kinds k on k.table_name = t.table_name and k.column_name = t.column_name
),
-- A correct spelling the column itself never uses is still a candidate.
candidates as (
    select distinct on (p.unit, p.b) p.unit, p.correct as value, 0 as records, p.b as k
    from typo_pairs p
    where exists (select 1 from keyed x where x.unit = p.unit and x.k = p.a)
      and not exists (select 1 from keyed x where x.unit = p.unit and x.k = p.b)
    order by p.unit, p.b, p.correct collate "C"
),
spellings as (
    select * from keyed union all select * from candidates
),
nodes as (
    select distinct unit, k from spellings
),
typo_edges as (
    select distinct p.unit, p.a, p.b from typo_pairs p
    where exists (select 1 from nodes n where n.unit = p.unit and n.k = p.a)
      and exists (select 1 from nodes n where n.unit = p.unit and n.k = p.b)
),
synonym_members as (
    select k.unit, s.synonym_set, {{ spelling_key('k.unit', 's.spelling') }} as k
    from {{ ref('synonyms') }} s
    join kinds k on k.table_name = s.table_name and k.column_name = s.column_name
    where exists (select 1 from nodes n where n.unit = k.unit and n.k = {{ spelling_key('k.unit', 's.spelling') }})
),
edges as (
    select unit, a, b from typo_edges
    union
    select m.unit, m.k, min(o.k collate "C")
    from synonym_members m join synonym_members o on o.unit = m.unit and o.synonym_set = m.synonym_set
    group by m.unit, m.synonym_set, m.k
),
both_ways as (
    select unit, a as x, b as y from edges union select unit, b, a from edges
),
reach (unit, k, r) as (
    select unit, k, k collate "C" from nodes
    union
    select reach.unit, reach.k, w.y collate "C" from reach join both_ways w on w.unit = reach.unit and w.x = reach.r
),
sets as (
    select unit, k, min(r collate "C") as root from reach group by unit, k
),
wrong as (
    select distinct unit, a as k from typo_edges
),
members as (
    select s.unit, s.value, s.records, s.k, x.root, w.k is not null as is_wrong,
           regexp_replace(btrim(s.value, {{ ws }}), '\s+', ' ', 'g') as normal
    from spellings s
    join sets x on x.unit = s.unit and x.k = s.k
    left join wrong w on w.unit = s.unit and w.k = s.k
),
-- Sets with nothing to change are left alone.
to_change as (
    select unit, root from members
    group by unit, root
    having count(distinct normal) > 1 or bool_or(value <> normal)
),
category as (
    select 'species' as unit, "Abbreviation" as spelling from {{ source('raw', 'SpeciesT') }}
    union all select 'species', code from {{ ref('species_added') }}
    union all select 'research_group', "Code" from {{ source('raw', 'ResearchGroupT') }}
    union all select 'vessel', "VesselCode" from {{ source('raw', 'VesselT') }}
    union all select 'DailyEventT.Code', "EventCode" from {{ source('raw', 'EventCodeT') }}
),
category_target as (
    select m.unit, m.root,
           min(regexp_replace(btrim(c.spelling, {{ ws }}), '\s+', ' ', 'g') collate "C") as target
    from members m
    join category c on c.unit = m.unit and {{ fn }}.key_text(c.spelling) = m.k
    group by m.unit, m.root
),
pool as (
    select m.unit, m.root, m.normal, sum(m.records) as total
    from members m
    where not m.is_wrong
       or not exists (select 1 from members o where o.unit = m.unit and o.root = m.root and not o.is_wrong)
    group by m.unit, m.root, m.normal
),
rule_target as (
    select distinct on (unit, root) unit, root, normal as target
    from pool
    order by unit, root,
             case when split_part(unit, '.', 2) ilike '%unit%' then {{ fn }}.unit_distance(normal)
                  else {{ fn }}.title_distance(normal) end,
             total desc, normal collate "C"
),
targets as (
    select c.unit, c.root, coalesce(ct.target, rt.target) as target
    from to_change c
    left join category_target ct on ct.unit = c.unit and ct.root = c.root
    left join rule_target rt on rt.unit = c.unit and rt.root = c.root
)
select m.unit, m.value as from_value, t.target as to_value,
       case when lower(m.normal) = lower(t.target) or m.k = {{ spelling_key('m.unit', 't.target') }}
            then case when m.normal <> t.target and lower(m.normal) = lower(t.target) then 'capitals' else 'spaces' end
            when m.is_wrong then 'typo'
            else 'synonym' end as kind
from members m
join targets t on t.unit = m.unit and t.root = m.root
where m.value <> t.target and m.records > 0
union all
select unit, value, to_value, 'corrected' from doug where value <> to_value
