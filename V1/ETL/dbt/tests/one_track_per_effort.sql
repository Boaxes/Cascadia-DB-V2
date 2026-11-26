-- An Effort has one track file at most. The Efforts in seeds/multi_track_efforts.csv
-- (DB167's DailyEffortID, and how many tracks each has) already had more when this
-- rule began, and keep what they have; no other Effort may have more than one, and
-- none of these may have more than its own number.
select e."DailyEffortID", count(*) as tracks, m.tracks as allowed
from {{ ref('TrackT') }} t
join {{ ref('DailyEffortT') }} e on e.id = t.daily_effort_id
left join {{ ref('multi_track_efforts') }} m on m.effort = e."DailyEffortID"
group by e."DailyEffortID", m.tracks
having count(*) > coalesce(m.tracks, 1)
