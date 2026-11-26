-- Efforts: the Efforts list and each effort's page. Every research group. id
-- is the hashed Primary Key; DB167's ID is legacy_daily_effort_id, which the
-- website's addresses use.
select id, "DailyEffortID" as legacy_daily_effort_id, "Research Group" as research_group,
       "Date"::date as effort_date, "Start Time" as start_time, "End Time" as end_time, vessel_id,
       "Locality" as locality, "Launch" as launch, "Return" as return_location, "Survey Type" as survey_type,
       "Region" as region, "Sub-area" as sub_area, "Project/Objective" as project_objective,
       "Personnel" as personnel, "Survey Comments" as survey_comments,
       "Time Off Effort"::interval as time_off_effort, "Total Survey Effort"::interval as total_survey_effort,
       total_distance_nm as distance_recorded_nm, st_y(start_point) as start_lat, st_x(start_point) as start_lon,
       start_point, start_coord_source, st_y(end_point) as end_lat, st_x(end_point) as end_lon, end_point,
       end_coord_source
from {{ ref('DailyEffortT') }} e
