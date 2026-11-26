{#
  When a build is swapped in, save every row its species and vessel lists gave
  a new id to, back into the list in raw. The list is where ids are kept, so
  the next build finds the row there and gives it the same id: an id never
  moves once given, and two builds from the same inputs agree. Saved at the
  swap rather than during the build, so a build that is never swapped in, or
  fails, leaves the lists as they were. Run inside the swap's transaction.
#}
{% macro remember_new_rows() %}
    insert into raw.species (species_id, code)
    select species_id, code from dbo{{ var('schema_suffix', '_next') }}."SpeciesT"
    where species_id not in (select species_id from raw.species)
    order by species_id;
    perform setval(pg_get_serial_sequence('raw.species', 'species_id'),
                   greatest((select max(species_id) from raw.species), 1));

    insert into raw.vessel_list (vessel_id, vessel_text, code, name, legacy_vessel_id)
    select vessel_id, vessel_text, code, name, legacy_vessel_id from dbo{{ var('schema_suffix', '_next') }}."VesselListT"
    where vessel_id not in (select vessel_id from raw.vessel_list)
    order by vessel_id;
    perform setval(pg_get_serial_sequence('raw.vessel_list', 'vessel_id'),
                   greatest((select max(vessel_id) from raw.vessel_list), 1));
{% endmacro %}


{#
  A record's vessel_id: the vessel its text names, ignoring case, or the one
  the website set; either way the id that stands for that vessel
  (models/dbo/lookups/vessel_for_text.sql). In a dbo model, with its rows as s:

      select ..., {{ vessel_id('s') }} as vessel_id
      from s ... {{ vessel_joins('s') }}
#}
{% macro vessel_id(relation) -%}
    case when {{ relation }}.__edits ? 'vessel_id' then vessel_edited.same_as
         else vessel_by_text.same_as end
{%- endmacro %}

{% macro vessel_joins(relation) -%}
    left join {{ ref('vessel_for_text') }} vessel_by_text
           on vessel_by_text.text_key = lower(btrim({{ relation }}."Vessel")) and vessel_by_text.first_of_text
    left join {{ ref('vessel_for_text') }} vessel_edited
           on vessel_edited.vessel_id = ({{ relation }}.__edits ->> 'vessel_id')::integer
{%- endmacro %}
