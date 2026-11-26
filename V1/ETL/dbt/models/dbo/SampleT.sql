-- SampleT: a biopsy or tissue sample collected at a sighting, with the
-- website's changes applied, plus its species and vessel.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R1  Trim surrounding whitespace and fold case-only spellings into the form the same research group uses most often in that column.
--      R2  "Species": the same species synonyms as sightings (macros/cleaning.sql).
--      SAM-001  "Sample Type", CRC only: variants of one sample type merged.
--               One-off field notes like 'mud? From antenna area' are kept.
--      SAM-003  "Certainty of Sample ID", CRC only: should be Positive,
--               Probable, Possible, Unknown or Negative. Numbers are cleared.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{% set spelled_columns = ["Sample Type", "Preservation", "Certainty of Sample ID", "Event", "Reaction", "Sampled by"] %}

with t as (select * from {{ source('raw', 'SampleT') }}),
{{ spelling_ctes('t', spelled_columns) }},
cleaned as (
    select
        t."SampleID" as "SampleID",
        t."DailyEffortID" as "DailyEffortID",
        t."SightingID" as "SightingID",
        t."SightingEventID" as "SightingEventID",
        t."IndividualID" as "IndividualID",
        {{ mapped('t."Species"', species_synonyms()) }} as "Species",
        t."Research Group" as "Research Group",
        t."Vessel" as "Vessel",
        t."Date" as "Date",
        t."Sighting" as "Sighting",
        t."SampleTime" as "SampleTime",
        t."Angle" as "Angle",
        case when t."Research Group" = 'CRC' and btrim({{ spelled("Certainty of Sample ID") }}) ~ '^[0-9]+$' then null
             else {{ spelled("Certainty of Sample ID") }} end as "Certainty of Sample ID",
        t."Distance" as "Distance",
        {{ spelled("Event") }} as "Event",
        t."Field ID" as "Field ID",
        {{ spelled("Preservation") }} as "Preservation",
        {{ spelled("Reaction") }} as "Reaction",
        t."Sample #" as "Sample #",
        t."Sample Number" as "Sample Number",
        t."Sample Photo" as "Sample Photo",
        case when t."Research Group" = 'CRC'
             then {{ mapped(spelled("Sample Type"), {'Skin': 'Skin Only Biopsy', 'Skin Only': 'Skin Only Biopsy',
                                                     'Sample-Other': 'Other', 'Blubber only': 'Blubber'}) }}
             else {{ spelled("Sample Type") }} end as "Sample Type",
        {{ spelled("Sampled by") }} as "Sampled by",
        t."SampleEvent" as "SampleEvent",
        t."Comments" as "Comments",
        t."SourceDB" as "SourceDB"
    from t {{ spelling_joins('t', spelled_columns) }}
),
r as (
    {{ replay_rows('cleaned', 'SampleT', 'SampleID') }}
),
s as (
    select {{ replayed_columns('SampleT', 'r') }}, r.__edits from r
)
select
    {{ column_list('SampleT', 's') }},
    -- A sample's own species code, synonyms applied (R2) and a trailing
    -- question mark trimmed.
    {{ edited('species_id', 'sp.species_id', 'integer', 's.__edits') }} as species_id,
    {{ vessel_id('s') }} as vessel_id
from s
left join {{ ref('SpeciesT') }} sp on sp.code = btrim(rtrim(btrim(s."Species"), '?'))
{{ vessel_joins('s') }}
