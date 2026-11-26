-- Samples on each sighting's page. Every research group.
select id, "SampleID" as legacy_sample_id, "Research Group" as research_group, sighting_id, daily_effort_id,
       vessel_id, species_id, coalesce("Sample #", "Sample Number") as sample_number, "Sample Type" as sample_type,
       "Date"::date + coalesce("SampleTime", '00:00:00'::time) as sample_datetime,
       "Certainty of Sample ID" as certainty_of_id, "Preservation" as preservation, "Sampled by" as sampled_by,
       "Field ID" as field_id, "Reaction" as reaction, "Comments" as comments
from {{ ref('SampleT') }} s
