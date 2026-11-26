-- Every depth whose unit is known has a depth in metres: metres, feet and
-- fathoms however they are written, and CRC's depths with no unit, which are
-- metres. The old pipeline left 'fath' and CRC's blank units empty.
select "SightingID", "Depth", "D units"
from {{ ref('SightingT') }}
where "Depth" is not null and depth_m is null
  and (lower(btrim("D units")) in ('m', 'meters', 'metres', 'ft', 'feet', 'fm', 'fath', 'fathoms')
       or (btrim(coalesce("D units", '')) = '' and "Research Group" = 'CRC' and "Depth" > 0))
