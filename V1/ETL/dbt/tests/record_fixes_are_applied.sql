-- Every fix in seeds/record_fixes.csv found its record and changed it: the
-- record named by its Legacy ID and date is there exactly once, and holds the
-- fix's new value. A fix that finds nothing, or whose old value the record no
-- longer holds, fails the build. So does a fix that changes nothing (its new
-- value is its old value, or DB167 now holds the new value itself), one that
-- repeats another, and one that fixes a column used in a Primary Key.
with records as (
    {%- for table, legacy in hashed_tables().items() if table in ('DailyEffortT', 'SightingT') %}
    select '{{ table }}' as table_name, "{{ legacy }}"::text as legacy_id, to_char("Date"::date, 'YYYY-MM-DD') as record_date,
           to_jsonb(k) as record
    from {{ ref('keyed_' ~ table) }} k
    {{ "union all" if not loop.last }}
    {%- endfor %}
),
raw_records as (
    {%- for table, legacy in hashed_tables().items() if table in ('DailyEffortT', 'SightingT') %}
    select '{{ table }}' as table_name, "{{ legacy }}"::text as legacy_id, to_char("Date"::date, 'YYYY-MM-DD') as record_date,
           to_jsonb(k) as record
    from {{ source('raw', table) }} k
    {{ "union all" if not loop.last }}
    {%- endfor %}
)
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'the record is not there, or is there more than once' as problem
from {{ ref('record_fixes') }} f
where (select count(*) from records r where r.table_name = f.table_name and r.legacy_id = f.legacy_id
       and r.record_date = f.record_date) <> 1
union all
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'the record does not hold the new value (it did not hold the old value)'
from {{ ref('record_fixes') }} f
join records r on r.table_name = f.table_name and r.legacy_id = f.legacy_id and r.record_date = f.record_date
where r.record ->> f.column_name is distinct from nullif(f.new_value, '')
union all
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'DB167 already holds the new value, so the fix does nothing'
from {{ ref('record_fixes') }} f
join raw_records r on r.table_name = f.table_name and r.legacy_id = f.legacy_id and r.record_date = f.record_date
where r.record ->> f.column_name is not distinct from nullif(f.new_value, '')
union all
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'the new value is the old value'
from {{ ref('record_fixes') }} f
where f.old_value is not distinct from nullif(f.new_value, '')
union all
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'the fix is listed more than once'
from {{ ref('record_fixes') }} f
group by f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule
having count(*) > 1
union all
select f.table_name, f.legacy_id, f.record_date, f.column_name, f.rule, 'the column is part of the Primary Key'
from {{ ref('record_fixes') }} f
where f.column_name in ('Research Group', 'Vessel', 'Date', 'Sighting')
