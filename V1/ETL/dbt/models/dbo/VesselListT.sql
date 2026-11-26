-- VesselListT: the category table of vessels (models/build/vessels.sql). Not in
-- DB167: one row per vessel in VesselT, and per vessel typed in the data that
-- VesselT does not have.
select vessel_id, code, name, legacy_vessel_id
from {{ ref('vessels') }}
