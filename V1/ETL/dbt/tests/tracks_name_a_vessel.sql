-- A track whose VesselID names no vessel in VesselT and which has no typed
-- Vessel and no EffortID is left out of dbo (models/dbo/TrackT.sql). None is
-- left in.
select t."TrackID"
from {{ source('raw', 'TrackT') }} t
join {{ ref('TrackT') }} d on d."TrackID" = t."TrackID"
where t."VesselID" is not null
  and nullif(btrim(t."Vessel"), '') is null
  and t."EffortID" is null
  and not exists (select 1 from {{ source('raw', 'VesselT') }} v where v."VesselID" = t."VesselID")
