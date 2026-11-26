-- A CRC sighting's start position has both a latitude and a longitude, or
-- neither (models/build/keyed_SightingT.sql). The website's edits are applied
-- after this, so they are not checked here.
select "SightingID"
from {{ ref('keyed_SightingT') }}
where "Research Group" = 'CRC'
  and ("Start Dec Lat" is null) <> ("Start Dec Long" is null)
