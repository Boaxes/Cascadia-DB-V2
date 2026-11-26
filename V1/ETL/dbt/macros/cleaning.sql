{#
  The cleaning steps that apply across a whole column.

  commonest_spelling: trim, then fold spellings that differ only in case into
  the one used most often in that column by the same research group, ties
  going to the alphabetically first so the result never depends on row order.
  Each group's rows follow that group's own majority: CRC writing "At Sea"
  keeps "At Sea", however often other groups wrote "at sea".

  Columns listed in `shared` are counted across every group instead: a
  species code is one vocabulary, matched against the species list, so every
  group's "Er" and "ER" must fold the same way.

      with t as (select * from {{ source('raw', 'SightingT') }}),
      {{ spelling_ctes('t', ['Species', 'Group Beh']) }}
      select {{ spelled('Species') }} as "Species", ...
      from t {{ spelling_joins('t', ['Species', 'Group Beh']) }}
#}
{% macro spelling_cte_name(column) -%}
    {{ adapter.quote('spelling: ' ~ column) }}
{%- endmacro %}

{% macro spelling_ctes(relation, columns, shared=[]) %}
    {%- for column in columns %}
    {{ spelling_cte_name(column) }} as (
        select research_group, key, value from (
            select research_group, lower(btrim(value)) as key, value,
                   row_number() over (partition by research_group, lower(btrim(value))
                                      order by n desc, value) as rank
            from (select {{ 'null::text' if column in shared else '"Research Group"' }} as research_group,
                         btrim({{ adapter.quote(column) }}) as value, count(*) as n
                  from {{ relation }} where {{ adapter.quote(column) }} is not null group by 1, 2) counts
        ) ranked
        where rank = 1
    ){{ "," if not loop.last }}
    {%- endfor %}
{% endmacro %}

{% macro spelling_joins(relation, columns, shared=[]) %}
    {%- for column in columns %}
    left join {{ spelling_cte_name(column) }}
           on {{ spelling_cte_name(column) }}.key = lower(btrim({{ relation }}.{{ adapter.quote(column) }}))
          {%- if column not in shared %}
          {#- An equality rather than IS NOT DISTINCT FROM, which Postgres can't
              hash: that made SightingT take half a minute to build. No
              table has an empty research group, so '' stands for none. #}
          and coalesce({{ spelling_cte_name(column) }}.research_group, '') = coalesce({{ relation }}."Research Group", '')
          {%- endif %}
    {%- endfor %}
{% endmacro %}

{% macro spelled(column, relation='t') -%}
    coalesce({{ spelling_cte_name(column) }}.value, {{ relation }}.{{ adapter.quote(column) }})
{%- endmacro %}

{#
  R7. A coordinate pair is a position only when it has both halves and
  neither is 0. Nobody surveys on the equator or the Greenwich meridian, so a
  0 means the position was not recorded, and half a pair names no place.
  Otherwise both halves are cleared.
#}
{% macro recorded_coordinate(value, lat, lon, relation='t') -%}
    case when {{ relation }}.{{ adapter.quote(lat) }} is null or {{ relation }}.{{ adapter.quote(lon) }} is null
           or {{ relation }}.{{ adapter.quote(lat) }} = 0 or {{ relation }}.{{ adapter.quote(lon) }} = 0
         then null else {{ relation }}.{{ adapter.quote(value) }} end
{%- endmacro %}


{#
  The vessel a track file's name gives, for a file DB167's file list has but
  no track record names: the letters and digits after the date, so
  20190703-KOH-tblt.csv, 20190703-KOH_2.csv and 20190703-KOH.csv are all
  vessel KOH. The old import took everything up to the next - or _, so a name
  with neither kept the rest of the name: "KOH.CSV", "ROB (2)".
#}
{% macro vessel_in_file_name(file_name) -%}
    upper(substring(btrim({{ file_name }}) from '^[0-9]{8}-([A-Za-z0-9]+)'))
{%- endmacro %}


{#
  Replace whole values by a list of spellings, matched ignoring case and
  surrounding whitespace, so a mapping still fires however R1 or the person
  typing it spelt the value. Anything not in the list is kept as it is.

      {{ mapped(spelled("Survey Type"), {'Land Observation': 'Land', 'ENT': 'Entanglement Response'}) }}
#}
{% macro mapped(expression, mapping) -%}
    case lower(btrim({{ expression }}))
    {%- for from, to in mapping.items() %}
        when '{{ from | lower | replace("'", "''") }}' then '{{ to | replace("'", "''") }}'
    {%- endfor %}
        else {{ expression }} end
{%- endmacro %}


{#
  R2. Species synonyms: different strings DB167 uses for the same animal, and
  the code each means. Used for sightings and samples alike, through mapped(),
  so case doesn't matter.
#}
{% macro species_synonyms() %}
    {{ return({'Zica': 'Zc', 'UD': 'UnDelph', 'UC': 'UnCet', 'Turtle': 'TURT-UN', 'UnTurt': 'TURT-UN',
               'LST': 'TURT-LB', 'Leatherback': 'TURT-LB', 'Olive Ridley Turtle': 'TURT-OR',
               'Dc.': 'Dc', 'bm.': 'Bm'}) }}
{% endmacro %}


{#
  A distance in nautical miles from text: a number, with or without a leading
  0 (.5), or a range (5-10), read as its midpoint; either may end in "nm".
  Anything else -- "<1", "20+", "3 miles", "G" -- is left empty.
#}
{% macro nautical_miles(text) -%}
    case when btrim({{ text }}) ~* '^[0-9]*\.?[0-9]+\s*(nm)?$'
         then substring(btrim({{ text }}) from '^[0-9]*\.?[0-9]+')::numeric
         when btrim({{ text }}) ~* '^[0-9]*\.?[0-9]+\s*-\s*[0-9]*\.?[0-9]+\s*(nm)?$'
         then (substring(btrim({{ text }}) from '^([0-9]*\.?[0-9]+)')::numeric
               + substring(btrim({{ text }}) from '-\s*([0-9]*\.?[0-9]+)')::numeric) / 2
    end
{%- endmacro %}
