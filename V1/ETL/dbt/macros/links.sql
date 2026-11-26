{#
  The Foreign Keys every table with a research group or vessel gets, found by
  its typed text, as dbo spells it (models/build/*_keys.sql). In a dbo model
  whose rows are s:

      select ..., rg.id as research_group_id, vk.vessel_id as vessel_id
      from s {{ group_and_vessel_joins('s') }}
#}
{% macro group_and_vessel_joins(relation) -%}
    left join {{ ref('research_group_keys') }} rg on rg.key = {{ build_fn() }}.key_text({{ relation }}."Research Group")
    left join {{ ref('vessel_keys') }} vk on vk.key = {{ build_fn() }}.key_text({{ relation }}."Vessel")
{%- endmacro %}


{# A typed species code's SpeciesID: an observer's trailing question mark left off. #}
{% macro species_join(relation, alias='sp') -%}
    left join {{ ref('species_keys') }} {{ alias }}
           on {{ alias }}.key = {{ build_fn() }}.key_text(rtrim(btrim({{ relation }}."Species"), '?'))
{%- endmacro %}


{#
  The usual start of a dbo model for one of the 8 tables with a hashed key:
  its kept rows (not exact copies), with the website's edits applied.

      with {{ replayed('DailyEventT') }}
      select s.id, {{ column_list('DailyEventT', 's') }}, ... from s

  A row the website created keeps the id the website gave it, which the audit
  log holds, so it is the same in every build. Its __effort and __sighting are
  read from its own values.
#}
{% macro replayed(table_name) %}
{%- set names = raw_column_names(table_name) -%}
rows as (
    select * from {{ ref('keyed_' ~ table_name) }} where not __is_copy
),
r as (
    {{ replay_rows('rows', table_name, 'id') }}
),
s0 as (
    select r.id, r.__key, {{ replayed_columns(table_name, 'r') }}, r.__edits
    {%- if 'Date' in names %}, r.__effort{% endif %}
    {%- if 'Sighting' in names %}, r.__sighting{% endif %}
    from r
),
s as (
    select coalesce(s0.id, case when s0.__key ~ '^[0-9]{1,18}$' then s0.__key::bigint
                                else {{ build_fn() }}.key_hash(array['created', s0.__key]) end) as id,
           {{ column_list(table_name, 's0') }}, s0.__edits
    {%- if 'Date' in names %},
           coalesce(s0.__effort, {{ key_hash(table_name, ['Research Group', 'Vessel', 'Date'], 's0') }}) as __effort
    {%- endif %}
    {%- if 'Sighting' in names %},
           coalesce(s0.__sighting, {{ key_hash(table_name, ['Research Group', 'Vessel', 'Date', 'Sighting'], 's0') }}) as __sighting
    {%- endif %}
    from s0
)
{% endmacro %}


{#
  The DB167 ID of the effort a track belongs to: the one it names, or for an
  effort DB167 has removed as a copy of another (seeds/removed_efforts.csv),
  the effort it kept.
#}
{% macro kept_effort(legacy) -%}
    coalesce((select r.kept_effort from {{ ref('removed_efforts') }} r
              where r.removed_effort = {{ legacy }}
                and not exists (select 1 from {{ ref('keyed_DailyEffortT') }} e where e."DailyEffortID" = {{ legacy }})),
             {{ legacy }})
{%- endmacro %}


{#
  Whether a track record names a vessel VesselT no longer has, and has no typed
  Vessel and no EffortID either: nothing says whose it is, so dbo leaves it out
  (models/dbo/TrackT.sql), and its file is treated as no track's
  (models/build/bucket_tracks.sql).
#}
{% macro track_names_no_vessel(relation) -%}
    ({{ relation }}."VesselID" is not null and {{ trimmed(relation ~ '."Vessel"') }} is null
     and {{ relation }}."EffortID" is null
     and not exists (select 1 from {{ source('raw', 'VesselT') }} v where v."VesselID" = {{ relation }}."VesselID"))
{%- endmacro %}
