-- DB167's own view, translated (was ETL/schema/dbo_views.sql). The list of
-- CRC IDs is in number order: DB167's view gave no order, so the list came out
-- in whatever order Postgres met the rows, and differed from build to build.
{{ config(materialized='view') }}
SELECT i."DailyEffortID", i."Research Group",
       string_agg(CAST(i."CRC ID" AS varchar(20)), ',' ORDER BY i."CRC ID", i."IdentificationID") AS "CRCID_list",
       i."Vessel", i."Date", i."Sighting", s."Start Time", s."SightingID"
FROM   {{ ref('IdentificationT') }} i
JOIN   {{ ref('SightingT') }} s
       ON i."Research Group" = s."Research Group" AND i."Vessel" = s."Vessel"
      AND i."Date" = s."Date" AND i."Sighting" = s."Sighting"
WHERE  i."CRC ID" IS NOT NULL
GROUP BY i."DailyEffortID", i."Research Group", i."Vessel", i."Date",
         i."Sighting", s."SightingID", s."Start Time"
