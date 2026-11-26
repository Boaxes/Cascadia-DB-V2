{#
  The hashed Primary Key, for the 8 tables whose DB167 IDs are not stable
  (models/build/keyed_*.sql). Each keyed model holds every DB167 row of its
  table, cleaned, with:

    id          the Primary Key: the combination of key columns hashed into one
                number (build.key_hash). Where records share the whole
                combination but differ in anything else, all are kept: the one
                with the lowest Legacy ID keeps the plain combination's id, and
                the others add their Legacy ID to it to tell them apart. (When
                DB167 removes such a duplicate it mostly keeps the lower ID, so
                the survivor mostly keeps its id.)
    __natural   the combination's hash on its own
    __shared    how many kept records share it
    __is_copy   an exact copy of another record, apart from the Legacy ID, the
                note of which import it came from (SourceDB), DB167's
                references to other records by their own IDs, and DB167's
                computed hash columns. One copy is kept, the one with the
                lowest Legacy ID; the others carry its id, so anything that
                pointed at them finds it.
    __effort    the hash of (Research Group, Vessel, Date): its effort's
    __sighting  the hash of (Research Group, Vessel, Date, Sighting): its sighting's

  Each part of a combination is read the same way everywhere (key_part), so
  a child's __effort is its effort's __natural.
#}

{# The 8 tables with a hashed Primary Key, and the Legacy ID column of each. #}
{% macro hashed_tables() %}
    {{ return({'DailyEffortT': 'DailyEffortID', 'DailyEventT': 'DailyEventID', 'DailyConditionT': 'DailyConditionID',
               'SightingT': 'SightingID', 'SightingEventT': 'SightingEventID', 'OtherSpeciesT': 'OtherSpeciesID',
               'SampleT': 'SampleID', 'IdentificationT': 'IdentificationID'}) }}
{% endmacro %}


{% macro not_compared() %}
    {{ return(['SourceDB', 'DailyEffortID', 'SightingID', 'SightingEventID', 'RG_hash', 'Vessel_hash', 'Sighting_hash']) }}
{% endmacro %}


{#- One part of a combination, as text. sources gives another expression to read a column from. -#}
{% macro key_part(table_name, column, relation='c', sources={}) -%}
    {%- set fn = build_fn() -%}
    {%- set cols = {} -%}
    {%- for c in raw_columns(table_name) -%}{%- do cols.update({c.name: c.data_type}) -%}{%- endfor -%}
    {%- set q = sources[column] if column in sources else relation ~ '.' ~ adapter.quote(column) -%}
    {%- if column not in cols -%}
        null::text
    {%- elif column == 'Date' -%}
        to_char({{ q }}::date, 'YYYY-MM-DD')
    {%- elif cols[column] in ('text', 'character varying') -%}
        {{ fn }}.key_text({{ q }})
    {%- elif cols[column].startswith('timestamp') -%}
        to_char({{ q }}, 'YYYY-MM-DD HH24:MI:SS.US')
    {%- else -%}
        {{ q }}::text
    {%- endif -%}
{%- endmacro %}


{% macro key_hash(table_name, columns, relation='c', extra=none, sources={}) -%}
    {%- set parts = [] -%}
    {%- for col in columns -%}{%- do parts.append(key_part(table_name, col, relation, sources)) -%}{%- endfor -%}
    {%- if extra is not none -%}{%- do parts.append(extra) -%}{%- endif -%}
    {{ build_fn() }}.key_hash(array[{{ parts | join(', ') }}])
{%- endmacro %}


{#
  key_raw  key columns whose id is made from the value DB167 has, not the value
           after spelling is made consistent, so that merging their variants
           (seeds/typos.csv) never changes a record's id.
#}
{% macro keyed_table(table_name, legacy, key_columns, overrides={}, key_raw=[]) %}
    {%- set names = raw_column_names(table_name) -%}
    {%- set from_raw = {} -%}
    {%- set from_kept = {} -%}
    {%- for col in key_raw -%}
        {%- do from_raw.update({col: 't.' ~ adapter.quote(col)}) -%}
        {%- do from_kept.update({col: 'kept.__key_' ~ loop.index}) -%}
    {%- endfor -%}
    {%- set compared = [] -%}
    {%- for n in names if n != legacy and n not in not_compared() -%}
        {%- do compared.append('t.' ~ adapter.quote(n)) -%}
    {%- endfor -%}
    {%- set l = adapter.quote(legacy) %}
with {{ cleaned_ctes(table_name, overrides, compared) }},
k as (
    select c.*,
    {%- for col in key_raw %}
           t.{{ adapter.quote(col) }} as __key_{{ loop.index }},
    {%- endfor %}
           {{ key_hash(table_name, key_columns, 'c', none, from_raw) }} as __natural
    from c
    {%- if key_raw %}
    join t on t.{{ l }} = c.{{ l }}
    {%- endif %}
),
copies as (
    select k.*, min(k.{{ l }}) over (partition by k.__natural, k.__content) as __kept
    from k
),
kept as (
    select copies.*, count(*) over (partition by copies.__natural) as __shared
    from copies where {{ l }} = __kept
),
ided as (
    select kept.*,
           case when __shared > 1 and {{ l }} <> min({{ l }}) over (partition by __natural)
                then {{ key_hash(table_name, key_columns, 'kept', l ~ '::text', from_kept) }}
                else __natural end as id
    from kept
),
everything as (
    select i.id, i.__natural, i.__shared, false as __is_copy, {{ column_list(table_name, 'i') }}
    from ided i
    union all
    select i.id, x.__natural, i.__shared, true, {{ column_list(table_name, 'x') }}
    from copies x join ided i on i.{{ l }} = x.__kept
    where x.{{ l }} <> x.__kept
)
select e.*
    {%- if 'Research Group' in names and 'Vessel' in names and 'Date' in names %},
       {{ key_hash(table_name, ['Research Group', 'Vessel', 'Date'], 'e') }} as __effort
    {%- endif %}
    {%- if 'Sighting' in names %},
       {{ key_hash(table_name, ['Research Group', 'Vessel', 'Date', 'Sighting'], 'e') }} as __sighting
    {%- endif %}
from everything e
{% endmacro %}


{#
  The id of a record's parent (an effort, a sighting): the kept record whose
  combination it shares. Where several share it, the one DB167's own reference
  (DailyEffortID, SightingID) names, if it is one of them; otherwise none.

      left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
      ... effort.id, effort.candidates
#}
{% macro parent_id(parent, parent_legacy, natural, legacy=none) -%}
    (
        select count(*) as candidates,
               case when count(*) = 1 then min(p.id)
                    {%- if legacy is not none %}
                    else min(p.id) filter (where p.id = (select l.id from {{ parent }} l
                                                         where l.{{ adapter.quote(parent_legacy) }} = {{ legacy }}))
                    {%- endif %}
               end as id
        from {{ parent }} p
        where p.__natural = {{ natural }} and not p.__is_copy
          -- A parent the website deleted is not there to point at.
          and not exists (select 1 from {{ ref('edit_rows') }} d
                          where d.target_table = '{{ parent.identifier | replace('keyed_', '') }}'
                            and d.state = 'deleted' and d.target_pk = p.id::text)
    )
{%- endmacro %}


{#
  Whether a record of one of the 8 tables is there once the audit log is
  applied: a kept DB167 record (not an exact copy) or one the website created,
  and not one the website deleted. For checking a Foreign Key a website edit
  set, where the parent's own dbo model cannot be read (it may read this one).

      where {{ exists_after_replay('DailyEffortT', 'v.id') }}
#}
{% macro exists_after_replay(table_name, id) -%}
    ((exists (select 1 from {{ ref('keyed_' ~ table_name) }} p where p.id = {{ id }} and not p.__is_copy)
      or exists (select 1 from {{ ref('edit_rows') }} c
                 where c.target_table = '{{ table_name }}' and c.state = 'created' and c.target_pk = {{ id }}::text))
     and not exists (select 1 from {{ ref('edit_rows') }} d
                     where d.target_table = '{{ table_name }}' and d.state = 'deleted' and d.target_pk = {{ id }}::text))
{%- endmacro %}


{# The id a DB167 ID stands for in one of the 8 tables (an exact copy's: its kept record's). #}
{% macro legacy_id(parent, parent_legacy, legacy) -%}
    (select l.id from {{ parent }} l where l.{{ adapter.quote(parent_legacy) }} = {{ legacy }})
{%- endmacro %}
