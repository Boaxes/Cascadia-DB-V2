-- A track's status is what its two facts say: is an effort linked, and is the
-- file stored (it has a row in raw.track_geometry). Nothing else sets it, so
-- a track linked without its status being updated -- the 11 tracks Doug
-- linked in V1 -- can't be left reading 'unassociated'.
select t."TrackID", t.track_status,
       case when t."EffortID" is not null and g.object_key is not null then 'available'
            when t."EffortID" is not null then 'missing_file'
            when g.object_key is not null then 'unassociated'
            else 'unresolved' end as follows
from {{ ref('TrackT') }} t
left join {{ source('raw', 'track_geometry') }} g on lower(g.object_key) = lower(t.file_name)
where t.track_status is distinct from
      case when t."EffortID" is not null and g.object_key is not null then 'available'
           when t."EffortID" is not null then 'missing_file'
           when g.object_key is not null then 'unassociated'
           else 'unresolved' end
