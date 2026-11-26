-- The species filter and names: every species any sighting uses.
select "SpeciesID" as id, "Abbreviation" as code, "CommonName" as common_name,
       nullif(btrim(concat_ws(' ', "Genus", "Species")), '') as scientific_name, category
from {{ ref('SpeciesT') }} sp
where exists (select 1 from {{ ref('SightingT') }} s where s.species_id = sp."SpeciesID")
