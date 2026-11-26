-- DB167's own views, translated. Access may bind to these, so the names and
-- output columns match what DB167 has today.
--
-- Mislabelled_IanRecsV is dropped: it joins DailyEffortT_IanDB_SnapshotT,
-- which is one of the two abandoned-migration tables this project does not
-- import (§3.2). Nothing currently uses it; ask before anyone needs it back.
--
-- SpeciesSummaryByEffortV: DB167's own catalog and its own view body disagree
-- on the name -- the body still says "CREATE VIEW dbo.SpeciesSummaryBySightingV"
-- from before someone renamed it. The catalog name is what Access binds to, so
-- that is what this uses.
--
-- SightingV drops one thing from the original: a LEFT JOIN to
-- SightingIdentificationT that is not used anywhere in the SELECT list. A join
-- like that only multiplies rows when a sighting has more than one
-- identification, which happens often (§3.8) -- so the original view already
-- risked duplicate rows for no reason. Removed rather than carried over.

CREATE VIEW dbo."DailyEffortV" AS
SELECT e."DailyEffortID", e."Research Group", e."Vessel", e."Date",
       e."Start Time", e."End Time", e."Distance Units", e."Launch",
       e."Locality", e."Personnel", e."PhotoDataBy", e."Project/Objective",
       e."Record Source", e."Region", e."Return", e."Sub-area",
       e."Survey Comments", e."Survey Type", e."Time Off Effort",
       e."Total Distance", e."Total Survey Effort", e."SourceDB",
       e."Start Dec Lat", e."Start Dec Long", e."End Dec Lat", e."End Dec Long",
       t."TrackFileName", t."TrackFileType", t."Useable", t."HitRate",
       t."TrackFileSize", t."Comments" AS "TrackComments",
       t."StartTime" AS "TrackStartTime", t."EndTime" AS "TrackEndTime",
       t."GPSPointCount", t."TrackDuration"
FROM   dbo."DailyEffortT" e
LEFT JOIN dbo."TrackT" t ON e."DailyEffortID" = t."EffortID"
WHERE  e."Research Group" = 'CRC';

CREATE VIEW dbo."SightingV" AS
SELECT s."SightingID", s."Research Group", s."Vessel", s."Date", s."Sighting",
       s."Species", s."Start Time", s."StartDateTime", s."Start Dec Lat",
       s."Start Dec Long", s."End Time", s."EndDateTime", s."End Dec Lat",
       s."End Dec Long", s."TargetDecLat", s."TargetDecLong", s."Est Size Best",
       s."Est Size Max", s."Est Size Min", s."Acoustics", s."Est ID",
       s."Actual ID", s."AltSighting", s."AltVessel", s."Angle", s."Bearing",
       s."CloseApproachCount", s."D units", s."Depth", s."DOT", s."Frames 1",
       s."Frames 2", s."Frames 3", s."GEX", s."GEY", s."Group Beh",
       s."Group Type", s."Heading", s."Height", s."Height1", s."Loc Code",
       s."LocDesc", s."Num Calves", s."Obs", s."Obs1", s."Other Beh 1",
       s."Other Beh 2", s."Other Beh 3", s."Permit", s."Photographer 1",
       s."Photographer 2", s."Photographer 3", s."Photos?", s."Position Type",
       s."PreyType", s."Range", s."RangeSource", s."RangeSource1", s."Reticle",
       s."Reticle1", s."Roll/File Number 1", s."Roll/File Number 2",
       s."Roll/File Number 3", s."Scattering", s."Series Number 1",
       s."Series Number 2", s."Series Number 3", s."Sight Type", s."Temp",
       s."Total Samples", s."Total Tags", s."Comments", s."SourceDB",
       s."RG_hash", s."Vessel_hash", s."Sighting_hash", s."DailyEffortID",
       se."SightEvent", o."Species" AS "OtherSpecies", sa."Sample Type"
FROM   dbo."SightingT" s
LEFT JOIN dbo."OtherSpeciesT" o
       ON s."Research Group" = o."Research Group" AND s."Vessel" = o."Vessel"
      AND s."Date" = o."Date" AND s."Sighting" = o."Sighting"
LEFT JOIN dbo."SightingEventT" se
       ON s."Research Group" = se."Research Group" AND s."Vessel" = se."Vessel"
      AND s."Date" = se."Date" AND s."Sighting" = se."Sighting"
LEFT JOIN dbo."SampleT" sa
       ON s."Research Group" = sa."Research Group" AND s."Vessel" = sa."Vessel"
      AND s."Date" = sa."Date" AND s."Sighting" = sa."Sighting";

CREATE VIEW dbo."SightingEffortTrackV" AS
SELECT s."SightingID" AS "Sighting_SightingID", s."Research Group" AS "Sighting_Research Group", s."Vessel" AS "Sighting_Vessel", s."Date" AS "Sighting_Date", s."Sighting" AS "Sighting_Sighting", s."Species" AS "Sighting_Species", s."Start Time" AS "Sighting_Start Time", s."StartDateTime" AS "Sighting_StartDateTime", s."Start Dec Lat" AS "Sighting_Start Dec Lat", s."Start Dec Long" AS "Sighting_Start Dec Long", s."End Time" AS "Sighting_End Time", s."EndDateTime" AS "Sighting_EndDateTime", s."End Dec Lat" AS "Sighting_End Dec Lat", s."End Dec Long" AS "Sighting_End Dec Long", s."TargetDecLat" AS "Sighting_TargetDecLat", s."TargetDecLong" AS "Sighting_TargetDecLong", s."Est Size Best" AS "Sighting_Est Size Best", s."Est Size Max" AS "Sighting_Est Size Max", s."Est Size Min" AS "Sighting_Est Size Min", s."Acoustics" AS "Sighting_Acoustics", s."Est ID" AS "Sighting_Est ID", s."Actual ID" AS "Sighting_Actual ID", s."AltSighting" AS "Sighting_AltSighting", s."AltVessel" AS "Sighting_AltVessel", s."Angle" AS "Sighting_Angle", s."Bearing" AS "Sighting_Bearing", s."CloseApproachCount" AS "Sighting_CloseApproachCount", s."D units" AS "Sighting_D units", s."Depth" AS "Sighting_Depth", s."DOT" AS "Sighting_DOT", s."Frames 1" AS "Sighting_Frames 1", s."Frames 2" AS "Sighting_Frames 2", s."Frames 3" AS "Sighting_Frames 3", s."GEX" AS "Sighting_GEX", s."GEY" AS "Sighting_GEY", s."Group Beh" AS "Sighting_Group Beh", s."Group Type" AS "Sighting_Group Type", s."Heading" AS "Sighting_Heading", s."Height" AS "Sighting_Height", s."Height1" AS "Sighting_Height1", s."Loc Code" AS "Sighting_Loc Code", s."LocDesc" AS "Sighting_LocDesc", s."Num Calves" AS "Sighting_Num Calves", s."Obs" AS "Sighting_Obs", s."Obs1" AS "Sighting_Obs1", s."Other Beh 1" AS "Sighting_Other Beh 1", s."Other Beh 2" AS "Sighting_Other Beh 2", s."Other Beh 3" AS "Sighting_Other Beh 3", s."Permit" AS "Sighting_Permit", s."Photographer 1" AS "Sighting_Photographer 1", s."Photographer 2" AS "Sighting_Photographer 2", s."Photographer 3" AS "Sighting_Photographer 3", s."Photos?" AS "Sighting_Photos?", s."Position Type" AS "Sighting_Position Type", s."PreyType" AS "Sighting_PreyType", s."Range" AS "Sighting_Range", s."RangeSource" AS "Sighting_RangeSource", s."RangeSource1" AS "Sighting_RangeSource1", s."Reticle" AS "Sighting_Reticle", s."Reticle1" AS "Sighting_Reticle1", s."Roll/File Number 1" AS "Sighting_Roll/File Number 1", s."Roll/File Number 2" AS "Sighting_Roll/File Number 2", s."Roll/File Number 3" AS "Sighting_Roll/File Number 3", s."Scattering" AS "Sighting_Scattering", s."Series Number 1" AS "Sighting_Series Number 1", s."Series Number 2" AS "Sighting_Series Number 2", s."Series Number 3" AS "Sighting_Series Number 3", s."Sight Type" AS "Sighting_Sight Type", s."Temp" AS "Sighting_Temp", s."Total Samples" AS "Sighting_Total Samples", s."Total Tags" AS "Sighting_Total Tags", s."Comments" AS "Sighting_Comments", s."SourceDB" AS "Sighting_SourceDB", s."RG_hash" AS "Sighting_RG_hash", s."Vessel_hash" AS "Sighting_Vessel_hash", s."Sighting_hash" AS "Sighting_Sighting_hash", s."DailyEffortID" AS "Sighting_DailyEffortID", s."SightEvent" AS "Sighting_SightEvent", s."OtherSpecies" AS "Sighting_OtherSpecies", s."Sample Type" AS "Sighting_Sample Type", d."DailyEffortID" AS "Effort_DailyEffortID", d."Research Group" AS "Effort_Research Group", d."Vessel" AS "Effort_Vessel", d."Date" AS "Effort_Date", d."Start Time" AS "Effort_Start Time", d."End Time" AS "Effort_End Time", d."Distance Units" AS "Effort_Distance Units", d."Launch" AS "Effort_Launch", d."Locality" AS "Effort_Locality", d."Personnel" AS "Effort_Personnel", d."PhotoDataBy" AS "Effort_PhotoDataBy", d."Project/Objective" AS "Effort_Project/Objective", d."Record Source" AS "Effort_Record Source", d."Region" AS "Effort_Region", d."Return" AS "Effort_Return", d."Sub-area" AS "Effort_Sub-area", d."Survey Comments" AS "Effort_Survey Comments", d."Survey Type" AS "Effort_Survey Type", d."Time Off Effort" AS "Effort_Time Off Effort", d."Total Distance" AS "Effort_Total Distance", d."Total Survey Effort" AS "Effort_Total Survey Effort", d."SourceDB" AS "Effort_SourceDB", d."Start Dec Lat" AS "Effort_Start Dec Lat", d."Start Dec Long" AS "Effort_Start Dec Long", d."End Dec Lat" AS "Effort_End Dec Lat", d."End Dec Long" AS "Effort_End Dec Long", d."TrackFileName" AS "Effort_TrackFileName", d."TrackFileType" AS "Effort_TrackFileType", d."Useable" AS "Effort_Useable", d."HitRate" AS "Effort_HitRate", d."TrackFileSize" AS "Effort_TrackFileSize", d."TrackComments" AS "Effort_TrackComments", d."TrackStartTime" AS "Effort_TrackStartTime", d."TrackEndTime" AS "Effort_TrackEndTime", d."GPSPointCount" AS "Effort_GPSPointCount", d."TrackDuration" AS "Effort_TrackDuration"
FROM dbo."SightingV" s
JOIN dbo."DailyEffortV" d ON d."DailyEffortID" = s."DailyEffortID"
WHERE d."TrackFileName" IS NOT NULL
  AND EXISTS (SELECT 1 FROM dbo."TrackFileList" f
              WHERE lower(trim(f."FileName")) = lower(trim(CAST(d."TrackFileName" AS text))));


CREATE VIEW dbo."TrackV" AS
SELECT t."TrackID", t."EffortID", t."ResearchGroupID", t."TrackCompleteCodeID",
       t."VesselID", t."SourceID", t."SurveyDate", t."TrackFileName",
       t."TrackFileType", t."Useable", t."HitRate", t."TrackFileSize",
       t."Comments", t."StartTime", t."EndTime", t."GPSPointCount",
       t."TrackDuration", s."Source", rg."Code" AS "Research Group",
       v."VesselName", v."VesselCode", tc."TrackCompleteCode"
FROM   dbo."TrackT" t
LEFT JOIN dbo."SourceT" s ON t."SourceID" = s."SourceID"
LEFT JOIN dbo."ResearchGroupT" rg ON t."ResearchGroupID" = rg."ResearchGroupID"
LEFT JOIN dbo."VesselT" v ON t."VesselID" = v."VesselID"
LEFT JOIN dbo."TrackCompleteCodeT" tc ON t."TrackCompleteCodeID" = tc."TrackCompleteCodeID";

CREATE VIEW dbo."TagSummaryV" AS
SELECT ts."TagSummaryID", ts."DailyEffortID", ts."Research Group", ts."Vessel",
       ts."Date", ts."Sighting", ts."Attachment", ts."CallTypes", ts."CEE",
       ts."DataCollected", ts."DeployBodyLoc", ts."DeployDateTime",
       ts."DeployRxn", ts."DeployTime", ts."DeployType", ts."Descriptions",
       ts."DiveTypes", ts."Field ID" AS "Field_ID", ts."GPSTrackSource",
       ts."HoursData", ts."HoursTotal", ts."PlaybackEnd", ts."PlaybackStart",
       ts."PlaybackType", ts."PreyData", ts."RecoverDateTime", ts."Segments",
       ts."SonarLogFilename", ts."Tag#" AS "TagNum", ts."TagDataFilename",
       ts."TagOffDateTime", ts."TagType", ts."VHFChannel", ts."Video",
       ts."TagComments", ts."SourceDB", s."Start Dec Lat", s."Start Dec Long",
       e."Launch", e."Locality", s."Species", s."Est Size Best"
FROM   dbo."TagSummaryT" ts
LEFT JOIN dbo."DailyEffortT" e ON ts."DailyEffortID" = e."DailyEffortID"
LEFT JOIN dbo."SightingT" s
       ON ts."Research Group" = s."Research Group" AND ts."Vessel" = s."Vessel"
      AND ts."Date" = s."Date" AND ts."Sighting" = s."Sighting";

CREATE VIEW dbo."IdentificationsBySightingV" AS
SELECT i."DailyEffortID", i."Research Group",
       string_agg(CAST(i."CRC ID" AS varchar(20)), ',') AS "CRCID_list",
       i."Vessel", i."Date", i."Sighting", s."Start Time", s."SightingID"
FROM   dbo."IdentificationT" i
JOIN   dbo."SightingT" s
       ON i."Research Group" = s."Research Group" AND i."Vessel" = s."Vessel"
      AND i."Date" = s."Date" AND i."Sighting" = s."Sighting"
WHERE  i."CRC ID" IS NOT NULL
GROUP BY i."DailyEffortID", i."Research Group", i."Vessel", i."Date",
         i."Sighting", s."SightingID", s."Start Time";

CREATE VIEW dbo."SpeciesSummaryByEffortV" AS
SELECT s."Species", sum(s."Est Size Best") AS "SpeciesCount", e."DailyEffortID"
FROM   dbo."SightingT" s
JOIN   dbo."DailyEffortT" e
       ON s."Research Group" = e."Research Group" AND s."Vessel" = e."Vessel"
      AND s."Date" = e."Date"
GROUP BY s."Species", e."DailyEffortID";
