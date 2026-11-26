-- app.daily_condition
create view app.daily_condition as
SELECT id,
    "DailyConditionID" AS legacy_daily_condition_id,
    "Research Group" AS research_group,
    daily_effort_id,
    vessel_id,
    "ConditionDateTime" AS condition_datetime,
    "ConditionTime" AS condition_time,
    st_y(geom) AS lat,
    st_x(geom) AS lon,
    geom,
    "Beaufort" AS beaufort,
    "Swell" AS swell_ft,
    "% Cloud Cover" AS cloud_cover_pct,
    "Precipitation" AS precipitation,
    "Quality" AS quality,
    visibility_nm,
    "Comments" AS comments
   FROM dbo."DailyConditionT" c;

-- app.daily_effort
create view app.daily_effort as
SELECT id,
    "DailyEffortID" AS legacy_daily_effort_id,
    "Research Group" AS research_group,
    ("Date")::date AS effort_date,
    "Start Time" AS start_time,
    "End Time" AS end_time,
    vessel_id,
    "Locality" AS locality,
    "Launch" AS launch,
    "Return" AS return_location,
    "Survey Type" AS survey_type,
    "Region" AS region,
    "Sub-area" AS sub_area,
    "Project/Objective" AS project_objective,
    "Personnel" AS personnel,
    "Survey Comments" AS survey_comments,
    ("Time Off Effort")::interval AS time_off_effort,
    ("Total Survey Effort")::interval AS total_survey_effort,
    total_distance_nm AS distance_recorded_nm,
    st_y(start_point) AS start_lat,
    st_x(start_point) AS start_lon,
    start_point,
    start_coord_source,
    st_y(end_point) AS end_lat,
    st_x(end_point) AS end_lon,
    end_point,
    end_coord_source
   FROM dbo."DailyEffortT" e;

-- app.daily_event
create view app.daily_event as
SELECT id,
    "DailyEventID" AS legacy_daily_event_id,
    "Research Group" AS research_group,
    daily_effort_id,
    vessel_id,
    "Code" AS code,
    "EventDateTime" AS event_datetime,
    "Time" AS event_time,
    st_y(geom) AS lat,
    st_x(geom) AS lon,
    geom,
    "ObsL" AS observer_left,
    "ObsR" AS observer_right,
    "Rec" AS recorder,
    "Comments" AS comments,
    event_code_id
   FROM dbo."DailyEventT" v;

-- app.effort_timeline
create view app.effort_timeline as
SELECT ('event:'::text || v."DailyEventID") AS row_key,
    v.daily_effort_id,
    'event'::text AS kind,
    v."EventDateTime" AS at,
    v."DailyEventID" AS legacy_id,
    st_y(v.geom) AS lat,
    st_x(v.geom) AS lon,
    v.geom,
    COALESCE(( SELECT (((c.name || ' ('::text) || c."EventCode") || ')'::text)
           FROM dbo."EventCodeT" c
          WHERE (c."EventCodeID" = v.event_code_id)), v."Code", 'log entry'::text) AS label
   FROM dbo."DailyEventT" v
UNION ALL
 SELECT ('sighting:'::text || s."SightingID") AS row_key,
    s.daily_effort_id,
    'sighting'::text AS kind,
    s."StartDateTime" AS at,
    s."SightingID" AS legacy_id,
    st_y(s.geom) AS lat,
    st_x(s.geom) AS lon,
    s.geom,
    COALESCE(( SELECT sp."CommonName"
           FROM dbo."SpeciesT" sp
          WHERE (sp."SpeciesID" = s.species_id)), s."Species", 'sighting'::text) AS label
   FROM dbo."SightingT" s
UNION ALL
 SELECT ('condition:'::text || c."DailyConditionID") AS row_key,
    c.daily_effort_id,
    'condition'::text AS kind,
    c."ConditionDateTime" AS at,
    c."DailyConditionID" AS legacy_id,
    st_y(c.geom) AS lat,
    st_x(c.geom) AS lon,
    c.geom,
    ('Beaufort '::text || COALESCE((c."Beaufort")::text, '?'::text)) AS label
   FROM dbo."DailyConditionT" c;

-- app.event_code
create view app.event_code as
SELECT "EventCodeID" AS id,
    "EventCode" AS code,
    name,
    "CodeDescription" AS description,
    "SortOrder" AS sort_order
   FROM dbo."EventCodeT" c;

-- app.sample
create view app.sample as
SELECT id,
    "SampleID" AS legacy_sample_id,
    "Research Group" AS research_group,
    sighting_id,
    daily_effort_id,
    vessel_id,
    species_id,
    COALESCE("Sample #", "Sample Number") AS sample_number,
    "Sample Type" AS sample_type,
    (("Date")::date + COALESCE("SampleTime", '00:00:00'::time without time zone)) AS sample_datetime,
    "Certainty of Sample ID" AS certainty_of_id,
    "Preservation" AS preservation,
    "Sampled by" AS sampled_by,
    "Field ID" AS field_id,
    "Reaction" AS reaction,
    "Comments" AS comments
   FROM dbo."SampleT" s;

-- app.sighting
create view app.sighting as
SELECT id,
    "SightingID" AS legacy_sighting_id,
    "Research Group" AS research_group,
    daily_effort_id,
    "Sighting" AS sighting_number,
    vessel_id,
    species_id,
    species_uncertain,
    "Species" AS species_raw,
    ("Date")::date AS sighting_date,
    "Start Time" AS sighting_time,
    "StartDateTime" AS sighting_datetime,
    st_y(geom) AS lat,
    st_x(geom) AS lon,
    geom,
    "End Dec Lat" AS end_lat,
    "End Dec Long" AS end_lon,
    end_geom,
    "Position Type" AS position_type,
    "Sight Type" AS sight_type,
    "Est Size Best" AS est_size_best,
    "Est Size Min" AS est_size_min,
    "Est Size Max" AS est_size_max,
    num_calves,
    "Group Beh" AS group_behavior,
    "Group Type" AS group_type,
    depth_m,
    "Photos?" AS photos_taken,
    "Comments" AS comments,
    identified_individual_count,
    "Bearing" AS bearing,
    "Range" AS range_m,
    "Reticle" AS reticle,
    "RangeSource" AS range_source,
    "Series Number 1" AS photo_series_1,
    "Frames 1" AS photo_frames_1,
    "Photographer 1" AS photographer_1
   FROM dbo."SightingT" s;

-- app.species
create view app.species as
SELECT "SpeciesID" AS id,
    "Abbreviation" AS code,
    "CommonName" AS common_name,
    NULLIF(btrim(concat_ws(' '::text, "Genus", "Species")), ''::text) AS scientific_name,
    category
   FROM dbo."SpeciesT" sp
  WHERE (EXISTS ( SELECT 1
           FROM dbo."SightingT" s
          WHERE (s.species_id = sp."SpeciesID")));

-- app.track
create view app.track as
SELECT "TrackID" AS id,
    "TrackID" AS legacy_track_id,
    "Research Group" AS research_group,
    daily_effort_id,
    file_name AS object_key,
    track_status,
    vessel_id,
    ( SELECT s."Source"
           FROM dbo."SourceT" s
          WHERE (s."SourceID" = t."SourceID")) AS track_source,
    ( SELECT c."TrackCompleteCode"
           FROM dbo."TrackCompleteCodeT" c
          WHERE (c."TrackCompleteCodeID" = t."TrackCompleteCodeID")) AS track_complete_code,
    "SurveyDate" AS survey_date,
    COALESCE("Useable", true) AS useable,
    geom,
    point_count,
    "StartTime" AS start_time_utc,
    "EndTime" AS end_time_utc,
    length_nm,
    "Comments" AS comments
   FROM dbo."TrackT" t;

-- app.vessel
create view app.vessel as
SELECT vessel_id AS id,
    legacy_vessel_id,
    code,
    COALESCE(name, code) AS name
   FROM dbo."VesselListT" v
  WHERE ((EXISTS ( SELECT 1
           FROM dbo."DailyEffortT" e
          WHERE (e.vessel_id = v.vessel_id))) OR (EXISTS ( SELECT 1
           FROM dbo."SightingT" s
          WHERE (s.vessel_id = v.vessel_id))));

-- dbo.DailyEffortV
create view dbo.DailyEffortV as
SELECT e."DailyEffortID",
    e."Research Group",
    e."Vessel",
    e."Date",
    e."Start Time",
    e."End Time",
    e."Distance Units",
    e."Launch",
    e."Locality",
    e."Personnel",
    e."PhotoDataBy",
    e."Project/Objective",
    e."Record Source",
    e."Region",
    e."Return",
    e."Sub-area",
    e."Survey Comments",
    e."Survey Type",
    e."Time Off Effort",
    e."Total Distance",
    e."Total Survey Effort",
    e."SourceDB",
    e."Start Dec Lat",
    e."Start Dec Long",
    e."End Dec Lat",
    e."End Dec Long",
    t."TrackFileName",
    t."TrackFileType",
    t."Useable",
    t."HitRate",
    t."TrackFileSize",
    t."Comments" AS "TrackComments",
    t."StartTime" AS "TrackStartTime",
    t."EndTime" AS "TrackEndTime",
    t."GPSPointCount",
    t."TrackDuration"
   FROM (dbo."DailyEffortT" e
     LEFT JOIN dbo."TrackT" t ON ((t.daily_effort_id = e.id)))
  WHERE (e."Research Group" = 'CRC'::text);

-- dbo.IdentificationsBySightingV
create view dbo.IdentificationsBySightingV as
SELECT i."DailyEffortID",
    i."Research Group",
    string_agg(((i."CRC ID")::character varying(20))::text, ','::text ORDER BY i."CRC ID") AS "CRCID_list",
    i."Vessel",
    i."Date",
    i."Sighting",
    s."Start Time",
    s."SightingID"
   FROM (dbo."IdentificationT" i
     JOIN dbo."SightingT" s ON ((s.id = i.sighting_id)))
  WHERE (i."CRC ID" IS NOT NULL)
  GROUP BY i."DailyEffortID", i."Research Group", i."Vessel", i."Date", i."Sighting", s."SightingID", s."Start Time";

-- dbo.SightingEffortTrackV
create view dbo.SightingEffortTrackV as
SELECT s."SightingID" AS "Sighting_SightingID",
    s."DailyEffortID" AS "Sighting_DailyEffortID",
    s."Research Group" AS "Sighting_Research Group",
    s."Vessel" AS "Sighting_Vessel",
    s."Date" AS "Sighting_Date",
    s."Sighting" AS "Sighting_Sighting",
    s."Species" AS "Sighting_Species",
    s."Start Time" AS "Sighting_Start Time",
    s."StartDateTime" AS "Sighting_StartDateTime",
    s."Start Dec Lat" AS "Sighting_Start Dec Lat",
    s."Start Dec Long" AS "Sighting_Start Dec Long",
    s."End Time" AS "Sighting_End Time",
    s."EndDateTime" AS "Sighting_EndDateTime",
    s."End Dec Lat" AS "Sighting_End Dec Lat",
    s."End Dec Long" AS "Sighting_End Dec Long",
    s."TargetDecLat" AS "Sighting_TargetDecLat",
    s."TargetDecLong" AS "Sighting_TargetDecLong",
    s."Est Size Best" AS "Sighting_Est Size Best",
    s."Est Size Max" AS "Sighting_Est Size Max",
    s."Est Size Min" AS "Sighting_Est Size Min",
    s."Acoustics" AS "Sighting_Acoustics",
    s."Est ID" AS "Sighting_Est ID",
    s."Actual ID" AS "Sighting_Actual ID",
    s."AltSighting" AS "Sighting_AltSighting",
    s."AltVessel" AS "Sighting_AltVessel",
    s."Angle" AS "Sighting_Angle",
    s."Bearing" AS "Sighting_Bearing",
    s."CloseApproachCount" AS "Sighting_CloseApproachCount",
    s."D units" AS "Sighting_D units",
    s."Depth" AS "Sighting_Depth",
    s."DOT" AS "Sighting_DOT",
    s."Frames 1" AS "Sighting_Frames 1",
    s."Frames 2" AS "Sighting_Frames 2",
    s."Frames 3" AS "Sighting_Frames 3",
    s."GEX" AS "Sighting_GEX",
    s."GEY" AS "Sighting_GEY",
    s."Group Beh" AS "Sighting_Group Beh",
    s."Group Type" AS "Sighting_Group Type",
    s."Heading" AS "Sighting_Heading",
    s."Height" AS "Sighting_Height",
    s."Height1" AS "Sighting_Height1",
    s."Loc Code" AS "Sighting_Loc Code",
    s."LocDesc" AS "Sighting_LocDesc",
    s."Num Calves" AS "Sighting_Num Calves",
    s."Obs" AS "Sighting_Obs",
    s."Obs1" AS "Sighting_Obs1",
    s."Other Beh 1" AS "Sighting_Other Beh 1",
    s."Other Beh 2" AS "Sighting_Other Beh 2",
    s."Other Beh 3" AS "Sighting_Other Beh 3",
    s."Permit" AS "Sighting_Permit",
    s."Photographer 1" AS "Sighting_Photographer 1",
    s."Photographer 2" AS "Sighting_Photographer 2",
    s."Photographer 3" AS "Sighting_Photographer 3",
    s."Photos?" AS "Sighting_Photos?",
    s."Position Type" AS "Sighting_Position Type",
    s."PreyType" AS "Sighting_PreyType",
    s."Range" AS "Sighting_Range",
    s."RangeSource" AS "Sighting_RangeSource",
    s."RangeSource1" AS "Sighting_RangeSource1",
    s."Reticle" AS "Sighting_Reticle",
    s."Reticle1" AS "Sighting_Reticle1",
    s."Roll/File Number 1" AS "Sighting_Roll/File Number 1",
    s."Roll/File Number 2" AS "Sighting_Roll/File Number 2",
    s."Roll/File Number 3" AS "Sighting_Roll/File Number 3",
    s."Scattering" AS "Sighting_Scattering",
    s."Series Number 1" AS "Sighting_Series Number 1",
    s."Series Number 2" AS "Sighting_Series Number 2",
    s."Series Number 3" AS "Sighting_Series Number 3",
    s."Sight Type" AS "Sighting_Sight Type",
    s."Temp" AS "Sighting_Temp",
    s."Total Samples" AS "Sighting_Total Samples",
    s."Total Tags" AS "Sighting_Total Tags",
    s."Comments" AS "Sighting_Comments",
    s."SourceDB" AS "Sighting_SourceDB",
    s."RG_hash" AS "Sighting_RG_hash",
    s."Vessel_hash" AS "Sighting_Vessel_hash",
    s."Sighting_hash" AS "Sighting_Sighting_hash",
    s."SightEvent" AS "Sighting_SightEvent",
    s."OtherSpecies" AS "Sighting_OtherSpecies",
    s."Sample Type" AS "Sighting_Sample Type",
    d."DailyEffortID" AS "Effort_DailyEffortID",
    d."Research Group" AS "Effort_Research Group",
    d."Vessel" AS "Effort_Vessel",
    d."Date" AS "Effort_Date",
    d."Start Time" AS "Effort_Start Time",
    d."End Time" AS "Effort_End Time",
    d."Distance Units" AS "Effort_Distance Units",
    d."Launch" AS "Effort_Launch",
    d."Locality" AS "Effort_Locality",
    d."Personnel" AS "Effort_Personnel",
    d."PhotoDataBy" AS "Effort_PhotoDataBy",
    d."Project/Objective" AS "Effort_Project/Objective",
    d."Record Source" AS "Effort_Record Source",
    d."Region" AS "Effort_Region",
    d."Return" AS "Effort_Return",
    d."Sub-area" AS "Effort_Sub-area",
    d."Survey Comments" AS "Effort_Survey Comments",
    d."Survey Type" AS "Effort_Survey Type",
    d."Time Off Effort" AS "Effort_Time Off Effort",
    d."Total Distance" AS "Effort_Total Distance",
    d."Total Survey Effort" AS "Effort_Total Survey Effort",
    d."SourceDB" AS "Effort_SourceDB",
    d."Start Dec Lat" AS "Effort_Start Dec Lat",
    d."Start Dec Long" AS "Effort_Start Dec Long",
    d."End Dec Lat" AS "Effort_End Dec Lat",
    d."End Dec Long" AS "Effort_End Dec Long",
    d."TrackFileName" AS "Effort_TrackFileName",
    d."TrackFileType" AS "Effort_TrackFileType",
    d."Useable" AS "Effort_Useable",
    d."HitRate" AS "Effort_HitRate",
    d."TrackFileSize" AS "Effort_TrackFileSize",
    d."TrackComments" AS "Effort_TrackComments",
    d."TrackStartTime" AS "Effort_TrackStartTime",
    d."TrackEndTime" AS "Effort_TrackEndTime",
    d."GPSPointCount" AS "Effort_GPSPointCount",
    d."TrackDuration" AS "Effort_TrackDuration"
   FROM (dbo."SightingV" s
     JOIN dbo."DailyEffortV" d ON ((d."DailyEffortID" = s."DailyEffortID")))
  WHERE ((d."TrackFileName" IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM build.db167_track_files f
          WHERE (f.name = lower(btrim(d."TrackFileName"))))));

-- dbo.SightingV
create view dbo.SightingV as
SELECT s."SightingID",
    s."DailyEffortID",
    s."Research Group",
    s."Vessel",
    s."Date",
    s."Sighting",
    s."Species",
    s."Start Time",
    s."StartDateTime",
    s."Start Dec Lat",
    s."Start Dec Long",
    s."End Time",
    s."EndDateTime",
    s."End Dec Lat",
    s."End Dec Long",
    s."TargetDecLat",
    s."TargetDecLong",
    s."Est Size Best",
    s."Est Size Max",
    s."Est Size Min",
    s."Acoustics",
    s."Est ID",
    s."Actual ID",
    s."AltSighting",
    s."AltVessel",
    s."Angle",
    s."Bearing",
    s."CloseApproachCount",
    s."D units",
    s."Depth",
    s."DOT",
    s."Frames 1",
    s."Frames 2",
    s."Frames 3",
    s."GEX",
    s."GEY",
    s."Group Beh",
    s."Group Type",
    s."Heading",
    s."Height",
    s."Height1",
    s."Loc Code",
    s."LocDesc",
    s."Num Calves",
    s."Obs",
    s."Obs1",
    s."Other Beh 1",
    s."Other Beh 2",
    s."Other Beh 3",
    s."Permit",
    s."Photographer 1",
    s."Photographer 2",
    s."Photographer 3",
    s."Photos?",
    s."Position Type",
    s."PreyType",
    s."Range",
    s."RangeSource",
    s."RangeSource1",
    s."Reticle",
    s."Reticle1",
    s."Roll/File Number 1",
    s."Roll/File Number 2",
    s."Roll/File Number 3",
    s."Scattering",
    s."Series Number 1",
    s."Series Number 2",
    s."Series Number 3",
    s."Sight Type",
    s."Temp",
    s."Total Samples",
    s."Total Tags",
    s."Comments",
    s."SourceDB",
    s."RG_hash",
    s."Vessel_hash",
    s."Sighting_hash",
    se."SightEvent",
    o."Species" AS "OtherSpecies",
    sa."Sample Type"
   FROM (((dbo."SightingT" s
     LEFT JOIN dbo."OtherSpeciesT" o ON ((o.sighting_id = s.id)))
     LEFT JOIN dbo."SightingEventT" se ON ((se.sighting_id = s.id)))
     LEFT JOIN dbo."SampleT" sa ON ((sa.sighting_id = s.id)));

-- dbo.SpeciesSummaryByEffortV
create view dbo.SpeciesSummaryByEffortV as
SELECT s."Species",
    sum(s."Est Size Best") AS "SpeciesCount",
    e."DailyEffortID"
   FROM (dbo."SightingT" s
     JOIN dbo."DailyEffortT" e ON ((e.id = s.daily_effort_id)))
  GROUP BY s."Species", e."DailyEffortID";

-- dbo.TagSummaryV
create view dbo.TagSummaryV as
SELECT ts."TagSummaryID",
    ts."DailyEffortID",
    ts."Research Group",
    ts."Vessel",
    ts."Date",
    ts."Sighting",
    ts."Attachment",
    ts."CallTypes",
    ts."CEE",
    ts."DataCollected",
    ts."DeployBodyLoc",
    ts."DeployDateTime",
    ts."DeployRxn",
    ts."DeployTime",
    ts."DeployType",
    ts."Descriptions",
    ts."DiveTypes",
    ts."Field ID" AS "Field_ID",
    ts."GPSTrackSource",
    ts."HoursData",
    ts."HoursTotal",
    ts."PlaybackEnd",
    ts."PlaybackStart",
    ts."PlaybackType",
    ts."PreyData",
    ts."RecoverDateTime",
    ts."Segments",
    ts."SonarLogFilename",
    ts."Tag#" AS "TagNum",
    ts."TagDataFilename",
    ts."TagOffDateTime",
    ts."TagType",
    ts."VHFChannel",
    ts."Video",
    ts."TagComments",
    ts."SourceDB",
    s."Start Dec Lat",
    s."Start Dec Long",
    e."Launch",
    e."Locality",
    s."Species",
    s."Est Size Best"
   FROM ((dbo."TagSummaryT" ts
     LEFT JOIN dbo."DailyEffortT" e ON ((e.id = ts.daily_effort_id)))
     LEFT JOIN dbo."SightingT" s ON ((s.id = ts.sighting_id)));

-- dbo.TrackV
create view dbo.TrackV as
SELECT t."TrackID",
    t."EffortID",
    t."ResearchGroupID",
    t."TrackCompleteCodeID",
    t."VesselID",
    t."SourceID",
    t."SurveyDate",
    t."TrackFileName",
    t."TrackFileType",
    t."Useable",
    t."HitRate",
    t."TrackFileSize",
    t."Comments",
    t."StartTime",
    t."EndTime",
    t."GPSPointCount",
    t."TrackDuration",
    s."Source",
    rg."Code" AS "Research Group",
    v."VesselName",
    v."VesselCode",
    tc."TrackCompleteCode"
   FROM ((((dbo."TrackT" t
     LEFT JOIN dbo."SourceT" s ON ((s."SourceID" = t."SourceID")))
     LEFT JOIN dbo."ResearchGroupT" rg ON ((rg."ResearchGroupID" = t."ResearchGroupID")))
     LEFT JOIN build.db167_vessels v ON ((v."VesselID" = t."VesselID")))
     LEFT JOIN dbo."TrackCompleteCodeT" tc ON ((tc."TrackCompleteCodeID" = t."TrackCompleteCodeID")));

