{{ config(materialized='updatable_view') }}
SELECT vessel_id       AS id,
       legacy_vessel_id,
       COALESCE(code, vessel_text)  AS code,
       COALESCE(name, vessel_text)  AS name
FROM   {{ ref('VesselListT') }} v
-- Only vessels CRC worked from, on the same reasoning.
WHERE  EXISTS (SELECT 1 FROM {{ ref('DailyEffortT') }} e
               WHERE e.vessel_id = v.vessel_id AND e."Research Group" = 'CRC')
   OR  EXISTS (SELECT 1 FROM {{ ref('SightingT') }} s
               WHERE s.vessel_id = v.vessel_id AND s."Research Group" = 'CRC')
