-- SpeciesT: the species list. raw.species keeps every species' id for good.
--
-- Its rows are raw.species, plus any code the sightings use that the list did
-- not have yet: SightingT gives such a code the next id, in code order, and it
-- is named by its code until someone names it in raw.species. Swapping the
-- build in saves those rows into raw.species, so the next build gives them the
-- same ids (macros/lists.sql).
with known as (
    select * from {{ source('raw', 'species') }}
),
new as (
    select distinct s.species_id, btrim(rtrim(btrim(s."Species"), '?')) as code
    from {{ ref('SightingT') }} s
    where s.species_id is not null
      and s.species_id not in (select species_id from known)
)
select species_id::integer    as species_id,
       code::text             as code,
       common_name::text      as common_name,
       scientific_name::text  as scientific_name,
       category::text         as category
from known
union all
select species_id::integer, code::text, null::text, null::text, 'unidentified'::text
from new
