{{ config(materialized='updatable_view') }}
SELECT sp.species_id AS id,
       sp.code,
       sp.common_name,
       sp.scientific_name,
       sp.category
FROM   {{ ref('SpeciesT') }} sp
-- Only codes CRC actually recorded. dbo holds every organisation's, and a
-- filter listing all 94 would offer species Cascadia has never seen.
WHERE  EXISTS (SELECT 1 FROM {{ ref('SightingT') }} s
               WHERE s.species_id = sp.species_id AND s."Research Group" = 'CRC')
