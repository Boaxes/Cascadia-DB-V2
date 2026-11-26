-- SpeciesT: DB167's species list, plus the codes sightings use that it lacks
-- (seeds/species_added.csv, with fixed SpeciesIDs from 1001), and category.
--
-- category is what the website groups species by: cetacean, pinniped,
-- other_marine, unidentified or non_animal: from seeds/species_categories.csv
-- for every code that list has, else from its Type.
{#- A code species_added.csv adds, column by column; any other column is NULL. -#}
{%- set added = {
    'SpeciesID': 'a.species_id',
    'CommonName': 'a.common_name',
    'Abbreviation': 'a.code',
    'Genus': "nullif(split_part(a.scientific_name, ' ', 1), '')",
    'Species': "nullif(substring(a.scientific_name from ' (.*)$'), '')",
} %}
with {{ cleaned_ctes('SpeciesT') }},
species as (
    select {{ column_list('SpeciesT', 'c') }} from c
    union all
    select {% for c in raw_columns('SpeciesT') %}{{ added.get(c.name, 'null') }} as {{ adapter.quote(c.name) }}{{ ', ' if not loop.last }}{% endfor %}
    from {{ ref('species_added') }} a
    where {{ build_fn() }}.key_text(a.code) not in
          (select {{ build_fn() }}.key_text("Abbreviation") from c where "Abbreviation" is not null)
)
select s.*,
       coalesce(k.category,
                case when s."Type" in ('Large whale', 'Small Cetacean', 'Toothed whale') then 'cetacean'
                     when s."Type" = 'Pinniped' then 'pinniped'
                     when s."Class" in ('Bird', 'Turtle') or s."Type" = 'Mustelidae' then 'other_marine'
                     else 'unidentified' end) as category
from species s
left join {{ ref('species_categories') }} k on {{ build_fn() }}.key_text(k.code) = {{ build_fn() }}.key_text(s."Abbreviation")
