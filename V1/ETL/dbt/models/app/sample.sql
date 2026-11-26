{{ config(materialized='updatable_view', meta={'check_option': true}) }}
SELECT s."SampleID"        AS id,
       s."SampleID"        AS legacy_sample_id,
       s."Research Group"  AS research_group,
       s."SightingID"      AS sighting_id,
       s."DailyEffortID"   AS daily_effort_id,
       s.vessel_id,
       s.species_id,
       COALESCE(s."Sample #", s."Sample Number") AS sample_number,
       s."Sample Type"     AS sample_type,
       -- The model wants one timestamp; DB167 keeps the day and the time apart.
       (s."Date"::date + COALESCE(s."SampleTime", '00:00'::time)) AS sample_datetime,
       s."Certainty of Sample ID" AS certainty_of_id,
       s."Preservation"    AS preservation,
       s."Sampled by"      AS sampled_by,
       s."Field ID"        AS field_id,
       s."Reaction"        AS reaction,
       s."Comments"        AS comments
FROM   {{ ref('SampleT') }} s
WHERE  s."Research Group" = 'CRC'
