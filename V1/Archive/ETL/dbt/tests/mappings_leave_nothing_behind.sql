-- A spelling a mapping replaces is gone from the table, however it was
-- capitalised. The old pipeline matched exact spellings after R1 had already
-- respelt some of them, so "ENTANGLEMENT" and one "Blubber only" were left.
select 'DailyEffortT' as table_name, "DailyEffortID" as id, "Survey Type" as value
from {{ ref('DailyEffortT') }}
where lower(btrim("Survey Type")) in ('non-standardized large vessel', 'land observation', 'entanglement', 'ent', 'uknown')
union all
select 'SampleT', "SampleID", "Sample Type" from {{ ref('SampleT') }}
where "Research Group" = 'CRC' and lower(btrim("Sample Type")) in ('skin', 'skin only', 'sample-other', 'blubber only')
union all
select 'SightingT', "SightingID", "Species" from {{ ref('SightingT') }}
where lower(btrim("Species")) in (
    {%- for from in species_synonyms() %}'{{ from | lower }}'{{ ", " if not loop.last }}{% endfor %})
