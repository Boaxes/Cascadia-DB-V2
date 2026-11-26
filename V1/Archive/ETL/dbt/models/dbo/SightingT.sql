-- SightingT: one observation of marine mammals, with the website's changes
-- applied, plus the columns DB167 has no room for.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R1  Trim surrounding whitespace and fold case-only spellings into the form the same research group uses most often in that column.
--      R2  "Species": Species synonyms: different strings for the same animal.
--      R7  a coordinate pair with a 0 in it, or with one half missing, is not a
--          position, and both halves are cleared.
--      CRD-002  "End Dec Lat" and "End Dec Long", CRC only: a longitude outside
--               plus or minus 180 can't be recovered, so the end position is cleared.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{% set spelled_columns = ["Species", "Group Beh", "Group Type", "Position Type", "Sight Type", "Other Beh 1", "Other Beh 2", "Other Beh 3", "Acoustics", "DOT", "PreyType", "RangeSource"] %}
{%- set fn = adapter.quote(this.schema) %}

{#- R5. Depth in metres, from the number and the unit recorded beside it.
    Left empty where the unit is unknown. A CRC depth with no unit is in
    metres: those are nearly all 2004 to 2006, when the unit wasn't filled
    in, and they spread like CRC's depths in metres, not its feet. A blank
    unit with a depth of 0 is left empty, as not recorded; other groups write
    feet as often as metres, so their blank units stay empty too. -#}
{% set depth_m %}
    case when s."Depth" is null then null
         when lower(btrim(coalesce(s."D units", ''))) in ('m', 'meters', 'metres')
           or (btrim(coalesce(s."D units", '')) = '' and s."Research Group" = 'CRC' and s."Depth" > 0)
         then round(s."Depth"::numeric, 2)
         when lower(btrim(s."D units")) in ('ft', 'feet')
         then round((s."Depth" * 0.3048)::numeric, 2)
         when lower(btrim(s."D units")) in ('fm', 'fath', 'fathoms')
         then round((s."Depth" * 1.8288)::numeric, 2)
    end
{% endset %}

{#- R6. The calf count, parsed out of a free-text column. A value like 1? is an
    observer who thinks they saw one, so it is left empty rather than counted
    as a confirmed calf. -#}
{% set num_calves %}
    case when s."Num Calves" ~ '^\s*[0-9]+\s*$' then btrim(s."Num Calves")::integer end
{% endset %}

with t as (select * from {{ source('raw', 'SightingT') }}),
{{ spelling_ctes('t', spelled_columns, shared=['Species']) }},
cleaned as (
    select
        t."SightingID" as "SightingID",
        t."DailyEffortID" as "DailyEffortID",
        t."Research Group" as "Research Group",
        t."Vessel" as "Vessel",
        t."Date" as "Date",
        t."Sighting" as "Sighting",
        {{ mapped(spelled("Species"), species_synonyms()) }} as "Species",
        t."Start Time" as "Start Time",
        t."StartDateTime" as "StartDateTime",
        {{ recorded_coordinate("Start Dec Lat", "Start Dec Lat", "Start Dec Long") }} as "Start Dec Lat",
        {{ recorded_coordinate("Start Dec Long", "Start Dec Lat", "Start Dec Long") }} as "Start Dec Long",
        t."End Time" as "End Time",
        t."EndDateTime" as "EndDateTime",
        case when t."Research Group" = 'CRC' and (t."End Dec Long" < -180 or t."End Dec Long" > 180) then null
             else {{ recorded_coordinate("End Dec Lat", "End Dec Lat", "End Dec Long") }} end as "End Dec Lat",
        case when t."Research Group" = 'CRC' and (t."End Dec Long" < -180 or t."End Dec Long" > 180) then null
             else {{ recorded_coordinate("End Dec Long", "End Dec Lat", "End Dec Long") }} end as "End Dec Long",
        t."TargetDecLat" as "TargetDecLat",
        t."TargetDecLong" as "TargetDecLong",
        t."Est Size Best" as "Est Size Best",
        t."Est Size Max" as "Est Size Max",
        t."Est Size Min" as "Est Size Min",
        {{ spelled("Acoustics") }} as "Acoustics",
        t."Est ID" as "Est ID",
        t."Actual ID" as "Actual ID",
        t."AltSighting" as "AltSighting",
        t."AltVessel" as "AltVessel",
        t."Angle" as "Angle",
        t."Bearing" as "Bearing",
        t."CloseApproachCount" as "CloseApproachCount",
        t."D units" as "D units",
        t."Depth" as "Depth",
        {{ spelled("DOT") }} as "DOT",
        t."Frames 1" as "Frames 1",
        t."Frames 2" as "Frames 2",
        t."Frames 3" as "Frames 3",
        t."GEX" as "GEX",
        t."GEY" as "GEY",
        {{ spelled("Group Beh") }} as "Group Beh",
        {{ spelled("Group Type") }} as "Group Type",
        t."Heading" as "Heading",
        t."Height" as "Height",
        t."Height1" as "Height1",
        t."Loc Code" as "Loc Code",
        t."LocDesc" as "LocDesc",
        t."Num Calves" as "Num Calves",
        t."Obs" as "Obs",
        t."Obs1" as "Obs1",
        {{ spelled("Other Beh 1") }} as "Other Beh 1",
        {{ spelled("Other Beh 2") }} as "Other Beh 2",
        {{ spelled("Other Beh 3") }} as "Other Beh 3",
        t."Permit" as "Permit",
        t."Photographer 1" as "Photographer 1",
        t."Photographer 2" as "Photographer 2",
        t."Photographer 3" as "Photographer 3",
        t."Photos?" as "Photos?",
        {{ spelled("Position Type") }} as "Position Type",
        {{ spelled("PreyType") }} as "PreyType",
        t."Range" as "Range",
        {{ spelled("RangeSource") }} as "RangeSource",
        t."RangeSource1" as "RangeSource1",
        t."Reticle" as "Reticle",
        t."Reticle1" as "Reticle1",
        t."Roll/File Number 1" as "Roll/File Number 1",
        t."Roll/File Number 2" as "Roll/File Number 2",
        t."Roll/File Number 3" as "Roll/File Number 3",
        t."Scattering" as "Scattering",
        t."Series Number 1" as "Series Number 1",
        t."Series Number 2" as "Series Number 2",
        t."Series Number 3" as "Series Number 3",
        {{ spelled("Sight Type") }} as "Sight Type",
        t."Temp" as "Temp",
        t."Total Samples" as "Total Samples",
        t."Total Tags" as "Total Tags",
        t."Comments" as "Comments",
        t."SourceDB" as "SourceDB",
        t."RG_hash" as "RG_hash",
        t."Vessel_hash" as "Vessel_hash",
        t."Sighting_hash" as "Sighting_hash"
    from t {{ spelling_joins('t', spelled_columns, shared=['Species']) }}
),
r as (
    {{ replay_rows('cleaned', 'SightingT', 'SightingID') }}
),
s as (
    select {{ replayed_columns('SightingT', 'r') }}, r.__edits from r
),
identifications as (
    select "SightingID", count(*) as n
    from {{ ref('SightingIdentificationT') }}
    group by 1
),
-- The species each sighting is filed under: its code, with a trailing question
-- mark trimmed, looked up in raw.species. A code the list does not have yet is
-- given the next id, in code order; SpeciesT then lists it, and saves it to
-- raw.species so the next build gives it the same id. A value naming more than
-- one species, like Bm/Bp, is not a species and gets none.
species_codes as (
    select distinct btrim(rtrim(btrim("Species"), '?')) as code
    from s
    where btrim(coalesce("Species", '')) <> ''
      and btrim(rtrim(btrim("Species"), '?')) <> ''
      and btrim("Species") !~ '[/,]'
),
species as (
    select code, species_id from {{ source('raw', 'species') }}
    union all
    select c.code,
           (select coalesce(max(species_id), 0) from {{ source('raw', 'species') }})
               + row_number() over (order by c.code) as species_id
    from species_codes c
    where c.code not in (select code from {{ source('raw', 'species') }})
)
select
    {{ column_list('SightingT', 's') }},
    {{ edited('identified_individual_count', 'coalesce(i.n, 0)', 'integer', 's.__edits') }} as identified_individual_count,
    {{ edited('geom', fn ~ '.point_from(s."Start Dec Lat", s."Start Dec Long")', 'geometry(Point,4326)', 's.__edits') }} as geom,
    {{ edited('end_geom', fn ~ '.point_from(s."End Dec Lat", s."End Dec Long")', 'geometry(Point,4326)', 's.__edits') }} as end_geom,
    {{ edited('num_calves', num_calves, 'integer', 's.__edits') }} as num_calves,
    {{ edited('depth_m', depth_m, 'numeric(10,2)', 's.__edits') }} as depth_m,
    -- The species this sighting is filed under (species, above).
    {{ edited('species_id', 'sp.species_id', 'integer', 's.__edits') }} as species_id,
    -- An observer's trailing question mark: the doubt belongs to the sighting.
    {{ edited('species_uncertain', 'coalesce(btrim(s."Species") like \'%?\', false)', 'boolean', 's.__edits') }} as species_uncertain,
    {{ vessel_id('s') }} as vessel_id
from s
left join identifications i on i."SightingID" = s."SightingID"
left join species sp on sp.code = btrim(rtrim(btrim(s."Species"), '?'))
    and btrim(s."Species") !~ '[/,]'
{{ vessel_joins('s') }}
