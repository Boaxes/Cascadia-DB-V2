-- DB167's own view, translated (was ETL/schema/dbo_views.sql).
{{ config(materialized='view') }}
SELECT s."SightingID", s."Research Group", s."Vessel", s."Date", s."Sighting",
       s."Species", s."Start Time", s."StartDateTime", s."Start Dec Lat",
       s."Start Dec Long", s."End Time", s."EndDateTime", s."End Dec Lat",
       s."End Dec Long", s."TargetDecLat", s."TargetDecLong", s."Est Size Best",
       s."Est Size Max", s."Est Size Min", s."Acoustics", s."Est ID",
       s."Actual ID", s."AltSighting", s."AltVessel", s."Angle", s."Bearing",
       s."CloseApproachCount", s."D units", s."Depth", s."DOT", s."Frames 1",
       s."Frames 2", s."Frames 3", s."GEX", s."GEY", s."Group Beh",
       s."Group Type", s."Heading", s."Height", s."Height1", s."Loc Code",
       s."LocDesc", s."Num Calves", s."Obs", s."Obs1", s."Other Beh 1",
       s."Other Beh 2", s."Other Beh 3", s."Permit", s."Photographer 1",
       s."Photographer 2", s."Photographer 3", s."Photos?", s."Position Type",
       s."PreyType", s."Range", s."RangeSource", s."RangeSource1", s."Reticle",
       s."Reticle1", s."Roll/File Number 1", s."Roll/File Number 2",
       s."Roll/File Number 3", s."Scattering", s."Series Number 1",
       s."Series Number 2", s."Series Number 3", s."Sight Type", s."Temp",
       s."Total Samples", s."Total Tags", s."Comments", s."SourceDB",
       s."RG_hash", s."Vessel_hash", s."Sighting_hash", s."DailyEffortID",
       se."SightEvent", o."Species" AS "OtherSpecies", sa."Sample Type"
FROM   {{ ref('SightingT') }} s
LEFT JOIN {{ ref('OtherSpeciesT') }} o
       ON s."Research Group" = o."Research Group" AND s."Vessel" = o."Vessel"
      AND s."Date" = o."Date" AND s."Sighting" = o."Sighting"
LEFT JOIN {{ ref('SightingEventT') }} se
       ON s."Research Group" = se."Research Group" AND s."Vessel" = se."Vessel"
      AND s."Date" = se."Date" AND s."Sighting" = se."Sighting"
LEFT JOIN {{ ref('SampleT') }} sa
       ON s."Research Group" = sa."Research Group" AND s."Vessel" = sa."Vessel"
      AND s."Date" = sa."Date" AND s."Sighting" = sa."Sighting"
