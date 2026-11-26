-- DB167's VesselT as it is, for dbo.TrackV. A copy rather than a view of raw,
-- so no view depends on raw and ETL/import_raw.py can replace it.
select "VesselID", "VesselCode", "VesselName" from {{ source('raw', 'VesselT') }}
