-- DB167's IdentificationsBySightingV: each sighting with the CRC IDs of the
-- animals identified in it, as one list in number order, so it is the same
-- every run. Found by the Foreign Key sighting_id.
select i."DailyEffortID", i."Research Group",
       string_agg(i."CRC ID"::varchar(20), ',' order by i."CRC ID") as "CRCID_list",
       i."Vessel", i."Date", i."Sighting", s."Start Time", s."SightingID"
from {{ ref('IdentificationT') }} i
join {{ ref('SightingT') }} s on s.id = i.sighting_id
where i."CRC ID" is not null
group by i."DailyEffortID", i."Research Group", i."Vessel", i."Date", i."Sighting", s."SightingID", s."Start Time"
