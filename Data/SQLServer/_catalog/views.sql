-- dbo.DailyEffortV
CREATE VIEW dbo.DailyEffortV
AS
SELECT e.DailyEffortID, e.[Research Group], e.Vessel, e.Date, e.[Start Time], e.[End Time], e.[Distance Units], e.Launch, e.Locality, e.Personnel, e.PhotoDataBy, e.[Project/Objective], e.[Record Source], e.Region, e.[Return], e.[Sub-area], e.[Survey Comments], e.[Survey Type], e.[Time Off Effort], 
             e.[Total Distance], e.[Total Survey Effort], e.SourceDB, e.[Start Dec Lat], e.[Start Dec Long], e.[End Dec Lat], e.[End Dec Long], t.TrackFileName, t.TrackFileType, t.Useable, t.HitRate, t.TrackFileSize, t.Comments AS TrackComments, t.StartTime AS TrackStartTime, 
             t.EndTime AS TrackEndTime, t.GPSPointCount, t.TrackDuration
FROM   dbo.DailyEffortT AS e LEFT OUTER JOIN
             dbo.TrackT AS t ON e.DailyEffortID = t.EffortID
WHERE (e.[Research Group] = 'CRC')
GO

-- dbo.DuplicateDailyEffortV
CREATE VIEW dbo.DuplicateDailyEffortV
AS

SELECT
    [Research Group],
    [Vessel],
    [Date],
    COUNT(*) AS DuplicateCount
FROM dbo.DailyEffortT
GROUP BY
    [Research Group],
    [Vessel],
    [Date]
HAVING COUNT(*) > 1;
GO

-- dbo.IanDB_DailyCondition_NotInDailyConditionV
/*
    dbo.IanDB_DailyCondition_NotInDailyConditionV

    Returns the IanDB weather and sea condition rows that do not appear in dbo.DailyConditionT,
    shaped exactly like dbo.DailyConditionT (same columns, order, types and nullability).

    Three steps:
        1. conv     Convert ConditionsT_IanDB_SnapshotT into the DailyConditionT format.
        2. missing  SELECT ... EXCEPT: find the identities (Vessel, Date, ConditionTime)
                    that exist in conv but not in DailyConditionT.
        3. Final    Join back to conv to return the full converted rows.

    Why only these columns go into the EXCEPT:
        DailyConditionT holds the CLEANED copy of this data, so comparing every column
        would report almost every row as missing. Research Group is left out on purpose:
        after 2003 the same group often appears under a different acronym in IanDB, and
        those rows are duplicates, not missing data.

    DailyConditionID is Ian's IanConditionID and DailyEffortID is Ian's effort id (see
    effort_ids). Neither is the final ID: the migration assigns new ones.
*/
CREATE   VIEW dbo.IanDB_DailyCondition_NotInDailyConditionV
AS

WITH

-- Ian's own effort id for each (Research Group, Vessel, Date), only where that triple is unique.
-- This is the same ID space as DailyEffortID in IanDB_DailyEffort_NotInDailyEffortV.
effort_ids AS (
    SELECT [Research Group], [Vessel], [EffortDate], MIN([EffortID]) AS EffortID
    FROM   dbo.DailyEffortT_IanDB_SnapshotT
    GROUP BY [Research Group], [Vessel], [EffortDate]
    HAVING COUNT(*) = 1
),

-- Step 1: IanDB rows renamed and cast to the exact DailyConditionT columns, in order.
conv AS (
    SELECT

        -- Ian's IanConditionID (the migration assigns the real ID)
        ISNULL(CAST(i.IanConditionID AS int), 0) AS [DailyConditionID],

        -- Ian's EffortID for the same Research Group, Vessel and Date; NULL if not unique
        CAST(e.EffortID AS int) AS [DailyEffortID],

        CAST(i.[Research Group] AS nvarchar(255)) AS [Research Group],

        CAST(i.Vessel AS nvarchar(255)) AS [Vessel],

        CAST(i.[Date] AS datetime) AS [Date],

        -- Date plus the time of day. Ian's Time is 1899-12-30 plus the time, so only the time part is used
        CAST(i.[Date] + CAST(CAST(i.[Time] AS time(0)) AS datetime) AS datetime) AS [ConditionDateTime],

        -- Time of day only
        CAST(CAST(i.[Time] AS time(0)) AS time(0)) AS [ConditionTime],

        CAST(i.[Dec Lat] AS float) AS [Dec Lat],

        CAST(i.[Dec Long] AS float) AS [Dec Long],

        CAST(i.[% Cloud Cover] AS int) AS [% Cloud Cover],

        CAST(i.Beaufort AS int) AS [Beaufort],

        CAST(i.Precipitation AS nvarchar(255)) AS [Precipitation],

        CAST(i.Quality AS nvarchar(255)) AS [Quality],

        CAST(i.Swell AS int) AS [Swell],

        CAST(i.Visibility AS nvarchar(255)) AS [Visibility],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Visibility (nm)],

        -- ntext in IanDB, nvarchar(max) here
        CAST(i.Comments AS nvarchar(max)) AS [Comments],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(50)) AS [SourceDB]

        -- Dropped (no place for them in DailyConditionT): Lat and Long (the text versions of the decimal position)

    FROM dbo.ConditionsT_IanDB_SnapshotT AS i
    LEFT JOIN effort_ids AS e
           ON  e.[Research Group] = i.[Research Group]
           AND e.[Vessel]         = i.[Vessel]
           AND e.[EffortDate]     = i.[Date]
),

-- Step 2: identities present in the converted IanDB rows but absent from DailyConditionT.
missing AS (
    SELECT [Vessel], [Date], [ConditionTime]
    FROM   conv

    EXCEPT

    SELECT [Vessel], [Date], [ConditionTime]
    FROM   dbo.DailyConditionT
)

-- Step 3: EXCEPT returns only the compared columns, so join back to conv to get full rows.
SELECT conv.*
FROM   conv
JOIN   missing AS m
       -- Date is never NULL in IanDB, so a plain equality lets SQL Server use a fast hash join.
       ON m.[Date] = conv.[Date]

       -- INTERSECT compares like EXCEPT does: two NULLs count as equal.
       AND EXISTS (
            SELECT conv.[Vessel], conv.[ConditionTime]
            INTERSECT
            SELECT m.[Vessel], m.[ConditionTime]
       );
GO

-- dbo.IanDB_DailyEffort_NotInDailyEffortV
/*
    dbo.IanDB_DailyEffort_NotInDailyEffortV

    Returns the IanDB efforts that do not appear in dbo.DailyEffortT, shaped
    exactly like DailyEffortT (same columns, order, types and nullability).

    Three steps:
        1. conv     Convert DailyEffortT_IanDB_SnapshotT into the DailyEffortT format.
        2. missing  SELECT ... EXCEPT: find the identities (Vessel, Date, Start Time,
                    End Time) that exist in conv but not in DailyEffortT.
        3. Final    Join back to conv to return the full converted rows.

    Why only four columns go into the EXCEPT:
        DailyEffortT holds the CLEANED copy of these efforts (survey types
        standardised, launch/return and coordinates fixed, flags set), so
        comparing every column would report almost every row as missing.
        To compare more or fewer columns, edit the column lists in "missing"
        and in the final join, and keep the two in step.
*/
CREATE   VIEW dbo.IanDB_DailyEffort_NotInDailyEffortV
AS

WITH

-- Step 1: IanDB rows renamed and cast to the exact DailyEffortT columns, in order.
conv AS (
    SELECT

        -- Ian's EffortID. Not the same number DailyEffortT uses for the same effort.
        ISNULL(CAST(i.EffortID AS int), 0)                  AS [DailyEffortID],

        CAST(i.[Research Group]    AS nvarchar(255))        AS [Research Group],
        CAST(i.Vessel              AS nvarchar(255))        AS [Vessel],

        -- Renamed: EffortDate -> Date
        CAST(i.EffortDate          AS datetime)             AS [Date],

        -- DailyEffortT stores times without fractions of a second, so time(0).
        CAST(i.[Start Time]        AS time(0))              AS [Start Time],
        CAST(i.[End Time]          AS time(0))              AS [End Time],

        -- Renamed: DIst Unit (sic) -> Distance Units
        CAST(i.[DIst Unit]         AS nvarchar(255))        AS [Distance Units],

        CAST(i.Launch              AS nvarchar(255))        AS [Launch],
        CAST(i.Locality            AS nvarchar(255))        AS [Locality],
        CAST(i.Personnel           AS nvarchar(255))        AS [Personnel],

        -- Not in IanDB, so NULL
        CAST(NULL                  AS nvarchar(255))        AS [PhotoDataBy],
        CAST(NULL                  AS datetime)             AS [PhotoDataDate],

        CAST(i.[Project/Objective] AS nvarchar(255))        AS [Project/Objective],

        -- Not in IanDB, so NULL
        CAST(NULL                  AS nvarchar(255))        AS [Record Source],

        CAST(i.Region              AS nvarchar(255))        AS [Region],
        CAST(i.[Return]            AS nvarchar(255))        AS [Return],
        CAST(i.[Sub-area]          AS nvarchar(255))        AS [Sub-area],
        CAST(i.[Survey Comments]   AS nvarchar(max))        AS [Survey Comments],

        -- Renamed: Survey type -> Survey Type
        CAST(i.[Survey type]       AS nvarchar(255))        AS [Survey Type],

        CAST(i.[Time Off Effort]   AS time(0))              AS [Time Off Effort],

        -- Ian stores Distance as a number, DailyEffortT as text.
        -- Round to 1 decimal and drop trailing zeros: 76.20 -> '76.2', 0 -> '0'.
        CAST(
            CASE WHEN i.Distance IS NULL
                 THEN NULL
                 ELSE FORMAT(ROUND(i.Distance, 1), '0.#')
            END
            AS nvarchar(255))                               AS [Total Distance],

        CAST(i.[Total Survey Effort] AS time(0))            AS [Total Survey Effort],

        -- Not in IanDB, so NULL
        CAST(NULL                  AS nvarchar(255))        AS [SourceDB],

        CAST(i.[Start Dec Lat]     AS float)                AS [Start Dec Lat],
        CAST(i.[Start Dec Long]    AS float)                AS [Start Dec Long],
        CAST(i.[End Dec Lat]       AS float)                AS [End Dec Lat],
        CAST(i.[End Dec Long]      AS float)                AS [End Dec Long],

        -- DailyEffortT does not allow NULL here, so NULL becomes 0.
        ISNULL(CAST(i.SentToAnnualDB AS bit), 0)            AS [SentToAnnualDB],

        -- IanDB has no Finalized flag, so every row gets 0.
        ISNULL(CAST(0 AS bit), 0)                           AS [Finalized],

        -- Not in IanDB, so NULL
        CAST(NULL                  AS nvarchar(50))         AS [MnSent],
        CAST(NULL                  AS nvarchar(50))         AS [BmSent],
        CAST(NULL                  AS nvarchar(50))         AS [ErSent]

        -- Dropped (DailyEffortT has no place for them): Launch Loc Code, Permit,
        -- CRCTrackFolder, AnnualDBID, Imported20251214, ImportedDate.

    FROM dbo.DailyEffortT_IanDB_SnapshotT AS i
),

-- Step 2: identities present in the converted IanDB rows but absent from DailyEffortT.
missing AS (
    SELECT [Vessel], [Date], [Start Time], [End Time]
    FROM   conv

    EXCEPT

    SELECT [Vessel], [Date], [Start Time], [End Time]
    FROM   dbo.DailyEffortT
)

-- Step 3: EXCEPT returns only the compared columns, so join back to conv to get full rows.
SELECT conv.*
FROM   conv
JOIN   missing AS m
       -- Date is never NULL in IanDB, so a plain equality lets SQL Server use a fast hash join.
       ON m.[Date] = conv.[Date]

       -- INTERSECT compares like EXCEPT does: two NULLs count as equal.
       -- A plain "=" would silently drop rows whose Vessel or times are NULL.
       AND EXISTS (
            SELECT conv.[Vessel], conv.[Start Time], conv.[End Time]
            INTERSECT
            SELECT m.[Vessel],    m.[Start Time],    m.[End Time]
       );
GO

-- dbo.IanDB_EffortLinksV
/* ------------------------------------------------------------------------------------------
   IanDB_EffortLinksV
   How each new condition, other species and sighting row would find its effort. The
   pipeline links them by Research Group, Vessel and Date, so a row finds an existing
   effort, a new IanDB effort the migration adds, or none (kept, with no effort link).
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_EffortLinksV
AS
WITH children AS (
    SELECT 'Conditions' AS t, [Research Group] AS rg, [Vessel] AS v, [Date] AS d FROM dbo.IanDB_DailyCondition_NotInDailyConditionV
    UNION ALL SELECT 'Other Species', [Research Group], [Vessel], [Date] FROM dbo.IanDB_OtherSpecies_NotInOtherSpeciesV
    UNION ALL SELECT 'Sightings', [Research Group], [Vessel], [Date] FROM dbo.IanDB_Sighting_NotInSightingV
),
-- Each effort key once, with where it comes from. Built once and joined, rather than looked
-- up row by row, so SQL Server can hash join it (a per-row lookup into the views timed out).
effort_keys AS (
    SELECT [Research Group] AS rg, [Vessel] AS v, [Date] AS d, MIN(src) AS src
    FROM (SELECT [Research Group], [Vessel], [Date], 1 AS src FROM dbo.DailyEffortT
          UNION ALL
          SELECT [Research Group], [Vessel], [Date], 2 FROM dbo.IanDB_EffortsToInsertV) AS k
    GROUP BY [Research Group], [Vessel], [Date]
),
linked AS (
    SELECT c.t,
           CASE k.src WHEN 1 THEN 'Existing Effort'
                      WHEN 2 THEN 'New IanDB Effort'
                      ELSE 'No Effort'
           END AS link
    FROM children c
    LEFT JOIN effort_keys k
           ON k.rg = c.rg AND k.v = c.v AND k.d = c.d
)
SELECT t AS [Table Name], link AS [Effort Link], COUNT(*) AS [Row Count]
FROM linked
GROUP BY t, link;
GO

-- dbo.IanDB_EffortsToInsertV
/*
    Views behind the "Issues Migrating IanDB Data" dashboard (ETL/migration/IanDB/dashboard).

    They build on the four conversion views (IanDB_*_NotIn*V) and answer two questions:
        1. What new data would the one-time migration bring in?
        2. What consistency issues would that data bring with it?

    Everything here is read only: views over DB167's tables, nothing stored.
    Run the whole file in SSMS (the GO lines separate the views).

    Text comparisons use the database's case-insensitive collation, which matches the
    pipeline: it folds spellings that differ only in case (cleaning rule R1).
*/


/* ------------------------------------------------------------------------------------------
   IanDB_EffortsToInsertV
   The efforts the migration would actually insert: the missing efforts, minus those whose
   Research Group, Vessel and Date already exist in DailyEffortT (the pipeline keys an effort
   on those three, so they would become duplicates), keeping one of any IanDB efforts that
   share the three among themselves. Same rule as IanDB_one_time_migration.sql.
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_EffortsToInsertV
AS
SELECT v.*
FROM (
    SELECT x.*,
           -- two IanDB efforts can share Research Group, Vessel and Date: keep the first
           ROW_NUMBER() OVER (PARTITION BY x.[Research Group], x.[Vessel], x.[Date]
                              ORDER BY x.[DailyEffortID]) AS rn
    FROM   dbo.IanDB_DailyEffort_NotInDailyEffortV AS x
) AS v
WHERE v.rn = 1
  AND NOT EXISTS (
        SELECT 1
        FROM   dbo.DailyEffortT AS d
        WHERE  d.[Research Group] = v.[Research Group]
          AND  d.[Vessel]         = v.[Vessel]
          AND  d.[Date]           = v.[Date]);
GO

-- dbo.IanDB_MigrationIssuesV
/* ------------------------------------------------------------------------------------------
   IanDB_MigrationIssuesV
   One row per (issue, value): a value the new rows would bring that the existing data
   never uses, so the pipeline's cleaning has no rule for it and it would appear on the
   website as typed. Row Count is how many new rows carry it.
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_MigrationIssuesV
AS
-- Each block counts the new rows per value first (a few hundred groups), then keeps the
-- values the existing data never uses: LEFT JOIN to the existing values, keep the misses.
-- (NOT IN / NOT EXISTS gave SQL Server a row-by-row plan here that took 10+ seconds.)

-- Survey types no existing effort uses (blank counts as an issue too)
SELECT 'Survey Type' AS [Issue], 'Efforts' AS [Table Name], ISNULL(g.val, '(Blank)') AS [Value], g.n AS [Row Count]
FROM      (SELECT [Survey Type] AS val, COUNT(*) AS n FROM dbo.IanDB_EffortsToInsertV GROUP BY [Survey Type]) AS g
LEFT JOIN (SELECT DISTINCT [Survey Type] AS val FROM dbo.DailyEffortT) AS o ON o.val = g.val
WHERE o.val IS NULL

UNION ALL
-- Sub-areas no existing effort uses
SELECT 'Sub-Area', 'Efforts', g.val, g.n
FROM      (SELECT [Sub-area] AS val, COUNT(*) AS n FROM dbo.IanDB_EffortsToInsertV GROUP BY [Sub-area]) AS g
LEFT JOIN (SELECT DISTINCT [Sub-area] AS val FROM dbo.DailyEffortT) AS o ON o.val = g.val
WHERE g.val IS NOT NULL AND o.val IS NULL

UNION ALL
-- Localities no existing effort uses
SELECT 'Locality', 'Efforts', g.val, g.n
FROM      (SELECT [Locality] AS val, COUNT(*) AS n FROM dbo.IanDB_EffortsToInsertV GROUP BY [Locality]) AS g
LEFT JOIN (SELECT DISTINCT [Locality] AS val FROM dbo.DailyEffortT) AS o ON o.val = g.val
WHERE g.val IS NOT NULL AND o.val IS NULL

UNION ALL
-- Vessel names no existing effort or sighting uses (the pipeline adds each as a new vessel)
SELECT 'Vessel', g.t, g.val, g.n
FROM      (SELECT t, v AS val, COUNT(*) AS n
           FROM (SELECT 'Efforts' AS t, [Vessel] AS v FROM dbo.IanDB_EffortsToInsertV
                 UNION ALL SELECT 'Sightings', [Vessel] FROM dbo.IanDB_Sighting_NotInSightingV) AS x
           GROUP BY t, v) AS g
LEFT JOIN (SELECT [Vessel] AS val FROM dbo.DailyEffortT
           UNION
           SELECT [Vessel] FROM dbo.SightingT) AS o ON o.val = g.val
WHERE g.val IS NOT NULL AND o.val IS NULL

UNION ALL
-- Research group codes no existing effort uses and ResearchGroupT does not list
SELECT 'Research Group', 'Efforts', g.val, g.n
FROM      (SELECT [Research Group] AS val, COUNT(*) AS n FROM dbo.IanDB_EffortsToInsertV GROUP BY [Research Group]) AS g
LEFT JOIN (SELECT [Research Group] AS val FROM dbo.DailyEffortT
           UNION
           SELECT [Code] FROM dbo.ResearchGroupT) AS o ON o.val = g.val
WHERE g.val IS NOT NULL AND o.val IS NULL

UNION ALL
-- Species codes not in SpeciesT. Question marks are ignored: the pipeline drops an
-- observer's trailing ?. The pipeline also knows a few codes SpeciesT lacks (its seed
-- lists of added species and synonyms), so this over-counts slightly.
SELECT 'Species Code', 'Sightings', g.val, g.n
FROM      (SELECT [Species] AS val, COUNT(*) AS n FROM dbo.IanDB_Sighting_NotInSightingV GROUP BY [Species]) AS g
LEFT JOIN (SELECT DISTINCT [Abbreviation] AS val FROM dbo.SpeciesT) AS o
       ON o.val = RTRIM(LTRIM(REPLACE(g.val, '?', '')))
WHERE g.val IS NOT NULL AND o.val IS NULL;
GO

-- dbo.IanDB_MigrationSummaryV
/* ------------------------------------------------------------------------------------------
   IanDB_MigrationSummaryV
   One row per table: how many rows IanDB has, how many the main table has, how many are
   missing from the main table, and how many the migration would add to the website once
   the pipeline has run (efforts: minus the skipped ones; other species: minus exact copies,
   which the pipeline keeps once).
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_MigrationSummaryV
AS
SELECT 1 AS [Sort], 'Efforts' AS [Table Name],
       (SELECT COUNT(*) FROM dbo.DailyEffortT_IanDB_SnapshotT)            AS [IanDB Rows],
       (SELECT COUNT(*) FROM dbo.DailyEffortT)                             AS [Main Table Rows],
       (SELECT COUNT(*) FROM dbo.IanDB_DailyEffort_NotInDailyEffortV)      AS [Missing Rows],
       (SELECT COUNT(*) FROM dbo.IanDB_EffortsToInsertV)                   AS [Rows Added]
UNION ALL
SELECT 2, 'Conditions',
       (SELECT COUNT(*) FROM dbo.ConditionsT_IanDB_SnapshotT),
       (SELECT COUNT(*) FROM dbo.DailyConditionT),
       (SELECT COUNT(*) FROM dbo.IanDB_DailyCondition_NotInDailyConditionV),
       (SELECT COUNT(*) FROM dbo.IanDB_DailyCondition_NotInDailyConditionV)
UNION ALL
SELECT 3, 'Other Species',
       (SELECT COUNT(*) FROM dbo.OtherSpeciesT_IanDB_SnapshotT),
       (SELECT COUNT(*) FROM dbo.OtherSpeciesT),
       (SELECT COUNT(*) FROM dbo.IanDB_OtherSpecies_NotInOtherSpeciesV),
       -- the pipeline keeps one of each set of rows identical in everything but their ID
       (SELECT COUNT(*) FROM (SELECT DISTINCT [Research Group], [Vessel], [Date], [Sighting], [Species],
                                              [Class], [Count], CAST([Comments] AS nvarchar(4000)) AS c
                              FROM dbo.IanDB_OtherSpecies_NotInOtherSpeciesV) AS d)
UNION ALL
SELECT 4, 'Sightings',
       (SELECT COUNT(*) FROM dbo.SightingT_IanDB_SnapShotT),
       (SELECT COUNT(*) FROM dbo.SightingT),
       (SELECT COUNT(*) FROM dbo.IanDB_Sighting_NotInSightingV),
       (SELECT COUNT(*) FROM dbo.IanDB_Sighting_NotInSightingV);
GO

-- dbo.IanDB_MissingByYearV
/* ------------------------------------------------------------------------------------------
   IanDB_MissingByYearV
   Per table and year: IanDB rows, main table rows, and rows missing from the main table.
   Era splits at Doug's line: 2003 and earlier was spreadsheets and never reconciled;
   2004 and later was reconciled by hand, so gaps there need a closer look.
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_MissingByYearV
AS
WITH counts AS (
    SELECT 'Efforts' AS t, YEAR([EffortDate]) AS y, 1 AS ian, 0 AS main, 0 AS missing FROM dbo.DailyEffortT_IanDB_SnapshotT
    UNION ALL SELECT 'Efforts', YEAR([Date]), 0, 1, 0 FROM dbo.DailyEffortT
    UNION ALL SELECT 'Efforts', YEAR([Date]), 0, 0, 1 FROM dbo.IanDB_DailyEffort_NotInDailyEffortV

    UNION ALL SELECT 'Conditions', YEAR([Date]), 1, 0, 0 FROM dbo.ConditionsT_IanDB_SnapshotT
    UNION ALL SELECT 'Conditions', YEAR([Date]), 0, 1, 0 FROM dbo.DailyConditionT
    UNION ALL SELECT 'Conditions', YEAR([Date]), 0, 0, 1 FROM dbo.IanDB_DailyCondition_NotInDailyConditionV

    UNION ALL SELECT 'Other Species', YEAR([Date]), 1, 0, 0 FROM dbo.OtherSpeciesT_IanDB_SnapshotT
    UNION ALL SELECT 'Other Species', YEAR([Date]), 0, 1, 0 FROM dbo.OtherSpeciesT
    UNION ALL SELECT 'Other Species', YEAR([Date]), 0, 0, 1 FROM dbo.IanDB_OtherSpecies_NotInOtherSpeciesV

    UNION ALL SELECT 'Sightings', YEAR([SightingDate]), 1, 0, 0 FROM dbo.SightingT_IanDB_SnapShotT
    UNION ALL SELECT 'Sightings', YEAR([Date]), 0, 1, 0 FROM dbo.SightingT
    UNION ALL SELECT 'Sightings', YEAR([Date]), 0, 0, 1 FROM dbo.IanDB_Sighting_NotInSightingV
)
SELECT t                                    AS [Table Name],
       y                                    AS [Year],
       SUM(ian)                             AS [IanDB Rows],
       SUM(main)                            AS [Main Table Rows],
       SUM(missing)                         AS [Missing Rows],
       CASE WHEN y <= 2003 THEN '2003 and Earlier' ELSE '2004 and Later' END AS [Era]
FROM counts
WHERE y IS NOT NULL
GROUP BY t, y;
GO

-- dbo.IanDB_OtherSpecies_NotInOtherSpeciesV
/*
    dbo.IanDB_OtherSpecies_NotInOtherSpeciesV

    Returns the IanDB other species rows that do not appear in dbo.OtherSpeciesT,
    shaped exactly like dbo.OtherSpeciesT (same columns, order, types and nullability).

    Three steps:
        1. conv     Convert OtherSpeciesT_IanDB_SnapshotT into the OtherSpeciesT format.
        2. missing  SELECT ... EXCEPT: find the identities (Vessel, Date, Sighting, Species)
                    that exist in conv but not in OtherSpeciesT.
        3. Final    Join back to conv to return the full converted rows.

    Why only these columns go into the EXCEPT:
        OtherSpeciesT holds the CLEANED copy of this data, so comparing every column
        would report almost every row as missing. Research Group is left out on purpose:
        after 2003 the same group often appears under a different acronym in IanDB, and
        those rows are duplicates, not missing data.

    IanDB has no ID column, so OtherSpeciesID is numbered 1, 2, 3... in a fixed order
    (Date, Vessel, Sighting, Species Code). The migration assigns the real ID.
    DailyEffortID is Ian's effort id (see effort_ids).
*/
CREATE   VIEW dbo.IanDB_OtherSpecies_NotInOtherSpeciesV
AS

WITH

-- Ian's own effort id for each (Research Group, Vessel, Date), only where that triple is unique.
-- This is the same ID space as DailyEffortID in IanDB_DailyEffort_NotInDailyEffortV.
effort_ids AS (
    SELECT [Research Group], [Vessel], [EffortDate], MIN([EffortID]) AS EffortID
    FROM   dbo.DailyEffortT_IanDB_SnapshotT
    GROUP BY [Research Group], [Vessel], [EffortDate]
    HAVING COUNT(*) = 1
),

-- Step 1: IanDB rows renamed and cast to the exact OtherSpeciesT columns, in order.
conv AS (
    SELECT

        -- Row number, because IanDB has no ID for these rows
        ISNULL(CAST(ROW_NUMBER() OVER (ORDER BY i.[Date], i.Vessel, i.Sighting, i.[Species Code], i.[Research Group], i.Class) AS int), 0) AS [OtherSpeciesID],

        -- Ian's EffortID for the same Research Group, Vessel and Date; NULL if not unique
        CAST(e.EffortID AS int) AS [DailyEffortID],

        CAST(i.[Research Group] AS nvarchar(255)) AS [Research Group],

        CAST(i.Vessel AS nvarchar(255)) AS [Vessel],

        CAST(i.[Date] AS datetime) AS [Date],

        CAST(i.Sighting AS nvarchar(255)) AS [Sighting],

        -- Renamed: Species Code -> Species
        CAST(i.[Species Code] AS nvarchar(255)) AS [Species],

        CAST(i.Class AS nvarchar(255)) AS [Class],

        -- Renamed: Number -> Count (float to int)
        CAST(i.Number AS int) AS [Count],

        CAST(i.Comments AS nvarchar(max)) AS [Comments],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(50)) AS [SourceDB]

        -- Dropped (no place for them in OtherSpeciesT): nothing (every IanDB column has a home)

    FROM dbo.OtherSpeciesT_IanDB_SnapshotT AS i
    LEFT JOIN effort_ids AS e
           ON  e.[Research Group] = i.[Research Group]
           AND e.[Vessel]         = i.[Vessel]
           AND e.[EffortDate]     = i.[Date]
),

-- Step 2: identities present in the converted IanDB rows but absent from OtherSpeciesT.
missing AS (
    SELECT [Vessel], [Date], [Sighting], [Species]
    FROM   conv

    EXCEPT

    SELECT [Vessel], [Date], [Sighting], [Species]
    FROM   dbo.OtherSpeciesT
)

-- Step 3: EXCEPT returns only the compared columns, so join back to conv to get full rows.
SELECT conv.*
FROM   conv
JOIN   missing AS m
       -- Date is never NULL in IanDB, so a plain equality lets SQL Server use a fast hash join.
       ON m.[Date] = conv.[Date]

       -- INTERSECT compares like EXCEPT does: two NULLs count as equal.
       AND EXISTS (
            SELECT conv.[Vessel], conv.[Sighting], conv.[Species]
            INTERSECT
            SELECT m.[Vessel], m.[Sighting], m.[Species]
       );
GO

-- dbo.IanDB_Sighting_NotInSightingV
/*
    dbo.IanDB_Sighting_NotInSightingV

    Returns the IanDB sighting rows that do not appear in dbo.SightingT,
    shaped exactly like dbo.SightingT (same columns, order, types and nullability).

    Three steps:
        1. conv     Convert SightingT_IanDB_SnapShotT into the SightingT format.
        2. missing  SELECT ... EXCEPT: find the identities (Vessel, Date, Sighting, Start Time)
                    that exist in conv but not in SightingT.
        3. Final    Join back to conv to return the full converted rows.

    Why only these columns go into the EXCEPT:
        SightingT holds the CLEANED copy of this data, so comparing every column
        would report almost every row as missing. Research Group is left out on purpose:
        after 2003 the same group often appears under a different acronym in IanDB, and
        those rows are duplicates, not missing data.

    SightingID is Ian's SightingID and DailyEffortID is Ian's effort id found by Research Group,
    Vessel and Date (see effort_ids). The migration assigns the real IDs.
    RG_hash, Vessel_hash and Sighting_hash are SHA2_256 of the text, as in SightingT.
*/
CREATE   VIEW dbo.IanDB_Sighting_NotInSightingV
AS

WITH

-- Ian's own effort id for each (Research Group, Vessel, Date), only where that triple is unique.
-- This is the same ID space as DailyEffortID in IanDB_DailyEffort_NotInDailyEffortV.
effort_ids AS (
    SELECT [Research Group], [Vessel], [EffortDate], MIN([EffortID]) AS EffortID
    FROM   dbo.DailyEffortT_IanDB_SnapshotT
    GROUP BY [Research Group], [Vessel], [EffortDate]
    HAVING COUNT(*) = 1
),

-- Step 1: IanDB rows renamed and cast to the exact SightingT columns, in order.
conv AS (
    SELECT

        -- Ian's SightingID (the migration assigns the real ID)
        ISNULL(CAST(i.SightingID AS int), 0) AS [SightingID],

        -- Ian's EffortID for the same Research Group, Vessel and Date; NULL if not unique. Ian's own sighting EffortID is not used: most point at no IanDB effort
        CAST(e.EffortID AS int) AS [DailyEffortID],

        CAST(i.[Research Group] AS nvarchar(255)) AS [Research Group],

        CAST(i.Vessel AS nvarchar(255)) AS [Vessel],

        -- Renamed: SightingDate -> Date
        CAST(i.SightingDate AS datetime) AS [Date],

        CAST(i.Sighting AS nvarchar(255)) AS [Sighting],

        CAST(i.Species AS nvarchar(255)) AS [Species],

        CAST(i.[Start Time] AS time(0)) AS [Start Time],

        -- Date plus Start Time (NULL when there is no time), as SightingT does
        CAST(i.SightingDate + CAST(i.[Start Time] AS datetime) AS datetime) AS [StartDateTime],

        CAST(i.[Start Dec Lat] AS float) AS [Start Dec Lat],

        CAST(i.[Start Dec Long] AS float) AS [Start Dec Long],

        CAST(i.[End Time] AS time(0)) AS [End Time],

        -- Date plus End Time (NULL when there is no time)
        CAST(i.SightingDate + CAST(i.[End Time] AS datetime) AS datetime) AS [EndDateTime],

        CAST(i.[End Dec Lat] AS float) AS [End Dec Lat],

        CAST(i.[End Dec Long] AS float) AS [End Dec Long],

        -- Renamed: TargetLatitude -> TargetDecLat
        CAST(i.TargetLatitude AS float) AS [TargetDecLat],

        -- Renamed: TargetLongitude -> TargetDecLong
        CAST(i.TargetLongitude AS float) AS [TargetDecLong],

        CAST(i.[Est Size Best] AS int) AS [Est Size Best],

        CAST(i.[Est Size Max] AS int) AS [Est Size Max],

        CAST(i.[Est Size Min] AS int) AS [Est Size Min],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(max)) AS [Acoustics],

        -- Renamed: EstIDs -> Est ID
        CAST(i.EstIDs AS int) AS [Est ID],

        -- Renamed: NumIDs -> Actual ID
        CAST(i.NumIDs AS int) AS [Actual ID],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [AltSighting],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [AltVessel],

        CAST(i.Angle AS int) AS [Angle],

        CAST(i.Bearing AS int) AS [Bearing],

        CAST(i.CloseApproachCount AS int) AS [CloseApproachCount],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [D units],

        CAST(i.Depth AS float) AS [Depth],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [DOT],

        CAST(i.[Frames 1] AS nvarchar(255)) AS [Frames 1],

        CAST(i.[Frames 2] AS nvarchar(255)) AS [Frames 2],

        CAST(i.[Frames 3] AS nvarchar(255)) AS [Frames 3],

        -- Not in IanDB, so NULL
        CAST(NULL AS int) AS [GEX],

        -- Not in IanDB, so NULL
        CAST(NULL AS int) AS [GEY],

        CAST(i.[Group Beh] AS nvarchar(255)) AS [Group Beh],

        CAST(i.[Group Type] AS nvarchar(255)) AS [Group Type],

        CAST(i.Heading AS int) AS [Heading],

        -- Renamed: EyeHeight -> Height
        CAST(i.EyeHeight AS float) AS [Height],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Height1],

        -- Not in IanDB, so NULL
        CAST(NULL AS int) AS [Loc Code],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [LocDesc],

        CAST(i.[Num Calves] AS nvarchar(255)) AS [Num Calves],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Obs],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Obs1],

        CAST(i.[Other Beh 1] AS nvarchar(255)) AS [Other Beh 1],

        CAST(i.[Other Beh 2] AS nvarchar(255)) AS [Other Beh 2],

        CAST(i.[Other Beh 3] AS nvarchar(255)) AS [Other Beh 3],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Permit],

        CAST(i.[Photographer 1] AS nvarchar(255)) AS [Photographer 1],

        CAST(i.[Photographer 2] AS nvarchar(255)) AS [Photographer 2],

        CAST(i.[Photographer 3] AS nvarchar(255)) AS [Photographer 3],

        -- Renamed: PhotosYN -> Photos?
        ISNULL(CAST(i.PhotosYN AS bit), 0) AS [Photos?],

        CAST(i.[Position Type] AS nvarchar(255)) AS [Position Type],

        CAST(i.PreyType AS nvarchar(255)) AS [PreyType],

        CAST(i.[Range] AS int) AS [Range],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [RangeSource],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [RangeSource1],

        -- Not in IanDB, so NULL
        CAST(NULL AS float) AS [Reticle],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Reticle1],

        -- Renamed: RollFile Number n -> Roll/File Number n
        CAST(i.[RollFile Number 1] AS nvarchar(255)) AS [Roll/File Number 1],

        CAST(i.[RollFile Number 2] AS nvarchar(255)) AS [Roll/File Number 2],

        CAST(i.[RollFile Number 3] AS nvarchar(255)) AS [Roll/File Number 3],

        CAST(i.Scattering AS nvarchar(max)) AS [Scattering],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Series Number 1],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Series Number 2],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(255)) AS [Series Number 3],

        CAST(i.[Sight Type] AS nvarchar(255)) AS [Sight Type],

        CAST(i.Temp AS nvarchar(255)) AS [Temp],

        -- Renamed: TotalSamples -> Total Samples
        CAST(i.TotalSamples AS int) AS [Total Samples],

        -- Renamed: TotalTags -> Total Tags
        CAST(i.TotalTags AS int) AS [Total Tags],

        CAST(i.Comments AS nvarchar(max)) AS [Comments],

        -- Not in IanDB, so NULL
        CAST(NULL AS nvarchar(50)) AS [SourceDB],

        -- SHA2_256 of the Research Group text, as in SightingT
        CAST(HASHBYTES('SHA2_256', CAST(i.[Research Group] AS nvarchar(255))) AS binary(32)) AS [RG_hash],

        -- SHA2_256 of the Vessel text
        CAST(HASHBYTES('SHA2_256', CAST(i.Vessel AS nvarchar(255))) AS binary(32)) AS [Vessel_hash],

        -- SHA2_256 of the Sighting text
        CAST(HASHBYTES('SHA2_256', CAST(i.Sighting AS nvarchar(255))) AS binary(32)) AS [Sighting_hash]

        -- Dropped (no place for them in SightingT): ResearchGroupID, SpeciesID, SpeciesCertaintyID, SightingTypeID, GroupBehaviorID, Feed, Reaction,
        -- PhotographerID, ImageSeriesName, StartFrame, EndFrame, RangeTypeID, and the text positions
        -- Start Lat, Start Long, End Lat, End Long

    FROM dbo.SightingT_IanDB_SnapShotT AS i
    LEFT JOIN effort_ids AS e
           ON  e.[Research Group] = i.[Research Group]
           AND e.[Vessel]         = i.[Vessel]
           AND e.[EffortDate]     = i.[SightingDate]
),

-- Step 2: identities present in the converted IanDB rows but absent from SightingT.
missing AS (
    SELECT [Vessel], [Date], [Sighting], [Start Time]
    FROM   conv

    EXCEPT

    SELECT [Vessel], [Date], [Sighting], [Start Time]
    FROM   dbo.SightingT
)

-- Step 3: EXCEPT returns only the compared columns, so join back to conv to get full rows.
SELECT conv.*
FROM   conv
JOIN   missing AS m
       -- Date is never NULL in IanDB, so a plain equality lets SQL Server use a fast hash join.
       ON m.[Date] = conv.[Date]

       -- INTERSECT compares like EXCEPT does: two NULLs count as equal.
       AND EXISTS (
            SELECT conv.[Vessel], conv.[Sighting], conv.[Start Time]
            INTERSECT
            SELECT m.[Vessel], m.[Sighting], m.[Start Time]
       );
GO

-- dbo.IanDB_SightingEffortIdCheckV
/* ------------------------------------------------------------------------------------------
   IanDB_SightingEffortIdCheckV
   Why the migration ignores IanDB's own effort ids: what each IanDB sighting's EffortID
   points at in the IanDB effort snapshot.
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_SightingEffortIdCheckV
AS
SELECT CASE WHEN e.[EffortID] IS NULL
                 THEN 'Points at No IanDB Effort'
            WHEN e.[Vessel] <> s.[Vessel] OR e.[EffortDate] <> s.[SightingDate]
                 THEN 'Points at a Different Vessel or Date'
            ELSE 'Points at the Right Effort'
       END        AS [Outcome],
       COUNT(*)   AS [Sighting Count]
FROM dbo.SightingT_IanDB_SnapShotT AS s
LEFT JOIN dbo.DailyEffortT_IanDB_SnapshotT AS e
       ON e.[EffortID] = s.[EffortID]
GROUP BY CASE WHEN e.[EffortID] IS NULL
                   THEN 'Points at No IanDB Effort'
              WHEN e.[Vessel] <> s.[Vessel] OR e.[EffortDate] <> s.[SightingDate]
                   THEN 'Points at a Different Vessel or Date'
              ELSE 'Points at the Right Effort'
         END;
GO

-- dbo.IanDB_SkippedEffortsV
/* ------------------------------------------------------------------------------------------
   IanDB_SkippedEffortsV
   The missing efforts the migration leaves out, each beside the DailyEffortT effort that
   already holds its Research Group, Vessel and Date (or the reason it was left out).
   ------------------------------------------------------------------------------------------ */
CREATE   VIEW dbo.IanDB_SkippedEffortsV
AS
SELECT
    v.[DailyEffortID]                  AS [IanEffortID],
    v.[Research Group],
    v.[Vessel],
    v.[Date],
    v.[Start Time]                     AS [Ian Start Time],
    v.[End Time]                       AS [Ian End Time],
    d.[DailyEffortID]                  AS [Existing DailyEffortID],
    d.[Start Time]                     AS [Existing Start Time],
    d.[End Time]                       AS [Existing End Time],
    CASE WHEN d.[DailyEffortID] IS NOT NULL
         THEN 'Effort With Same Group, Vessel and Date Already Exists'
         ELSE 'Second IanDB Effort With Same Group, Vessel and Date'
    END                                AS [Reason]
FROM dbo.IanDB_DailyEffort_NotInDailyEffortV AS v
LEFT JOIN dbo.DailyEffortT AS d
       ON  d.[Research Group] = v.[Research Group]
       AND d.[Vessel]         = v.[Vessel]
       AND d.[Date]           = v.[Date]
WHERE NOT EXISTS (SELECT 1 FROM dbo.IanDB_EffortsToInsertV AS i
                  WHERE i.[DailyEffortID] = v.[DailyEffortID]);
GO

-- dbo.IdentificationsBySightingV
CREATE VIEW dbo.IdentificationsBySightingV
AS
SELECT dbo.IdentificationT.DailyEffortID, dbo.IdentificationT.[Research Group], STRING_AGG(CONVERT(varchar(20), dbo.IdentificationT.[CRC ID]), ',') AS CRCID_list, dbo.IdentificationT.Vessel, dbo.IdentificationT.Date, dbo.IdentificationT.Sighting, dbo.SightingT.[Start Time], 
             dbo.SightingT.SightingID
FROM   dbo.IdentificationT INNER JOIN
             dbo.SightingT ON dbo.IdentificationT.[Research Group] = dbo.SightingT.[Research Group] AND dbo.IdentificationT.Vessel = dbo.SightingT.Vessel AND dbo.IdentificationT.Date = dbo.SightingT.Date AND dbo.IdentificationT.Sighting = dbo.SightingT.Sighting
WHERE (dbo.IdentificationT.[CRC ID] IS NOT NULL)
GROUP BY dbo.IdentificationT.DailyEffortID, dbo.IdentificationT.[Research Group], dbo.IdentificationT.Vessel, dbo.IdentificationT.Date, dbo.IdentificationT.Sighting, dbo.SightingT.SightingID, dbo.SightingT.[Start Time]
GO

-- dbo.Mislabelled_IanRecsV
CREATE VIEW dbo.Mislabelled_IanRecsV
AS
SELECT a.RecSource, a.[Research Group], a.EffortDate, a.ThisVessel AS Vessel, b.RecSource AS IanRecs, c.EffortID AS IanEffortID, c.[Research Group] AS IanRG, c.Vessel AS IanVessel, c.EffortDate AS IanDate, c.Locality, c.[Survey type], c.Personnel
FROM   dbo.EffortProblemT AS a INNER JOIN
             dbo.EffortProblemT AS b ON a.LinkedProblemID = b.ProblemID INNER JOIN
             dbo.DailyEffortT_IanDB_SnapshotT AS c ON b.DailyEffortNum = c.EffortID
WHERE (a.RecSource = 'AnnualDBUnion')
GO

-- dbo.SampleEventSightingV
CREATE VIEW dbo.SampleEventSightingV
AS

SELECT
    s.[Research Group],
    s.[Vessel],
    s.[Date],
    s.[Sighting],
    ss.[Species],
    CAST(ss.[StartDateTime] AS time(0)) AS StartTime,
    s.[SampleTime],
    s.[Event],
    s.[Field ID],
    s.[Sample #],
    s.[Sample Number],
    s.[Sampled by],
    s.[Latitude],
    s.[Longitude],
    e.[Dec Lat],
    e.[Dec Long],
    e.[Field ID] AS EventFieldID,
    e.[SightEvent]
FROM dbo.SampleT AS s

INNER JOIN dbo.SightingEventT AS e
    ON s.[Research Group] = e.[Research Group]
    AND s.[Vessel] = e.[Vessel]
    AND s.[Date] = e.[Date]
    AND s.[Sighting] = e.[Sighting]
    AND s.[Field ID] = e.[Field ID]

INNER JOIN dbo.SightingT AS ss
    ON s.[Research Group] = ss.[Research Group]
    AND s.[Vessel] = ss.[Vessel]
    AND s.[Date] = ss.[Date]
    AND s.[Sighting] = ss.[Sighting]

WHERE
    e.[SightEvent] LIKE '%Sample%';
GO

-- dbo.SightingEffortTrackV
CREATE   VIEW dbo.SightingEffortTrackV
AS
SELECT
    s.[SightingID] AS [Sighting_SightingID],
    s.[Research Group] AS [Sighting_Research Group],
    s.[Vessel] AS [Sighting_Vessel],
    s.[Date] AS [Sighting_Date],
    s.[Sighting] AS [Sighting_Sighting],
    s.[Species] AS [Sighting_Species],
    s.[Start Time] AS [Sighting_Start Time],
    s.[StartDateTime] AS [Sighting_StartDateTime],
    s.[Start Dec Lat] AS [Sighting_Start Dec Lat],
    s.[Start Dec Long] AS [Sighting_Start Dec Long],
    s.[End Time] AS [Sighting_End Time],
    s.[EndDateTime] AS [Sighting_EndDateTime],
    s.[End Dec Lat] AS [Sighting_End Dec Lat],
    s.[End Dec Long] AS [Sighting_End Dec Long],
    s.[TargetDecLat] AS [Sighting_TargetDecLat],
    s.[TargetDecLong] AS [Sighting_TargetDecLong],
    s.[Est Size Best] AS [Sighting_Est Size Best],
    s.[Est Size Max] AS [Sighting_Est Size Max],
    s.[Est Size Min] AS [Sighting_Est Size Min],
    s.[Acoustics] AS [Sighting_Acoustics],
    s.[Est ID] AS [Sighting_Est ID],
    s.[Actual ID] AS [Sighting_Actual ID],
    s.[AltSighting] AS [Sighting_AltSighting],
    s.[AltVessel] AS [Sighting_AltVessel],
    s.[Angle] AS [Sighting_Angle],
    s.[Bearing] AS [Sighting_Bearing],
    s.[CloseApproachCount] AS [Sighting_CloseApproachCount],
    s.[D units] AS [Sighting_D units],
    s.[Depth] AS [Sighting_Depth],
    s.[DOT] AS [Sighting_DOT],
    s.[Frames 1] AS [Sighting_Frames 1],
    s.[Frames 2] AS [Sighting_Frames 2],
    s.[Frames 3] AS [Sighting_Frames 3],
    s.[GEX] AS [Sighting_GEX],
    s.[GEY] AS [Sighting_GEY],
    s.[Group Beh] AS [Sighting_Group Beh],
    s.[Group Type] AS [Sighting_Group Type],
    s.[Heading] AS [Sighting_Heading],
    s.[Height] AS [Sighting_Height],
    s.[Height1] AS [Sighting_Height1],
    s.[Loc Code] AS [Sighting_Loc Code],
    s.[LocDesc] AS [Sighting_LocDesc],
    s.[Num Calves] AS [Sighting_Num Calves],
    s.[Obs] AS [Sighting_Obs],
    s.[Obs1] AS [Sighting_Obs1],
    s.[Other Beh 1] AS [Sighting_Other Beh 1],
    s.[Other Beh 2] AS [Sighting_Other Beh 2],
    s.[Other Beh 3] AS [Sighting_Other Beh 3],
    s.[Permit] AS [Sighting_Permit],
    s.[Photographer 1] AS [Sighting_Photographer 1],
    s.[Photographer 2] AS [Sighting_Photographer 2],
    s.[Photographer 3] AS [Sighting_Photographer 3],
    s.[Photos?] AS [Sighting_Photos?],
    s.[Position Type] AS [Sighting_Position Type],
    s.[PreyType] AS [Sighting_PreyType],
    s.[Range] AS [Sighting_Range],
    s.[RangeSource] AS [Sighting_RangeSource],
    s.[RangeSource1] AS [Sighting_RangeSource1],
    s.[Reticle] AS [Sighting_Reticle],
    s.[Reticle1] AS [Sighting_Reticle1],
    s.[Roll/File Number 1] AS [Sighting_Roll/File Number 1],
    s.[Roll/File Number 2] AS [Sighting_Roll/File Number 2],
    s.[Roll/File Number 3] AS [Sighting_Roll/File Number 3],
    s.[Scattering] AS [Sighting_Scattering],
    s.[Series Number 1] AS [Sighting_Series Number 1],
    s.[Series Number 2] AS [Sighting_Series Number 2],
    s.[Series Number 3] AS [Sighting_Series Number 3],
    s.[Sight Type] AS [Sighting_Sight Type],
    s.[Temp] AS [Sighting_Temp],
    s.[Total Samples] AS [Sighting_Total Samples],
    s.[Total Tags] AS [Sighting_Total Tags],
    s.[Comments] AS [Sighting_Comments],
    s.[SourceDB] AS [Sighting_SourceDB],
    s.[RG_hash] AS [Sighting_RG_hash],
    s.[Vessel_hash] AS [Sighting_Vessel_hash],
    s.[Sighting_hash] AS [Sighting_Sighting_hash],
    s.[DailyEffortID] AS [Sighting_DailyEffortID],
    s.[SightEvent] AS [Sighting_SightEvent],
    s.[OtherSpecies] AS [Sighting_OtherSpecies],
    s.[Sample Type] AS [Sighting_Sample Type],
    d.[DailyEffortID] AS [Effort_DailyEffortID],
    d.[Research Group] AS [Effort_Research Group],
    d.[Vessel] AS [Effort_Vessel],
    d.[Date] AS [Effort_Date],
    d.[Start Time] AS [Effort_Start Time],
    d.[End Time] AS [Effort_End Time],
    d.[Distance Units] AS [Effort_Distance Units],
    d.[Launch] AS [Effort_Launch],
    d.[Locality] AS [Effort_Locality],
    d.[Personnel] AS [Effort_Personnel],
    d.[PhotoDataBy] AS [Effort_PhotoDataBy],
    d.[Project/Objective] AS [Effort_Project/Objective],
    d.[Record Source] AS [Effort_Record Source],
    d.[Region] AS [Effort_Region],
    d.[Return] AS [Effort_Return],
    d.[Sub-area] AS [Effort_Sub-area],
    d.[Survey Comments] AS [Effort_Survey Comments],
    d.[Survey Type] AS [Effort_Survey Type],
    d.[Time Off Effort] AS [Effort_Time Off Effort],
    d.[Total Distance] AS [Effort_Total Distance],
    d.[Total Survey Effort] AS [Effort_Total Survey Effort],
    d.[SourceDB] AS [Effort_SourceDB],
    d.[Start Dec Lat] AS [Effort_Start Dec Lat],
    d.[Start Dec Long] AS [Effort_Start Dec Long],
    d.[End Dec Lat] AS [Effort_End Dec Lat],
    d.[End Dec Long] AS [Effort_End Dec Long],
    d.[TrackFileName] AS [Effort_TrackFileName],
    d.[TrackFileType] AS [Effort_TrackFileType],
    d.[Useable] AS [Effort_Useable],
    d.[HitRate] AS [Effort_HitRate],
    d.[TrackFileSize] AS [Effort_TrackFileSize],
    d.[TrackComments] AS [Effort_TrackComments],
    d.[TrackStartTime] AS [Effort_TrackStartTime],
    d.[TrackEndTime] AS [Effort_TrackEndTime],
    d.[GPSPointCount] AS [Effort_GPSPointCount],
    d.[TrackDuration] AS [Effort_TrackDuration]
FROM dbo.SightingV AS s
INNER JOIN dbo.DailyEffortV AS d
    ON d.DailyEffortID = s.DailyEffortID
WHERE d.TrackFileName IS NOT NULL
  AND EXISTS
  (
      SELECT 1
      FROM dbo.TrackFileList AS f
      WHERE LOWER(LTRIM(RTRIM(f.FileName))) =
            LOWER(LTRIM(RTRIM(
                CAST(d.TrackFileName AS nvarchar(max))
            )))
  );
GO

-- dbo.SightingEventSummaryByEffortV
CREATE VIEW dbo.SightingEventSummaryByEffortV
AS
SELECT [Research Group], Vessel, Date, SightEvent, COUNT(*) AS EventCount
FROM   dbo.SightingEventT
GROUP BY [Research Group], Vessel, Date, SightEvent
GO

-- dbo.SightingV
CREATE VIEW dbo.SightingV
AS
SELECT s.SightingID, s.[Research Group], s.Vessel, s.Date, s.Sighting, s.Species, s.[Start Time], s.StartDateTime, s.[Start Dec Lat], s.[Start Dec Long], s.[End Time], s.EndDateTime, s.[End Dec Lat], s.[End Dec Long], s.TargetDecLat, s.TargetDecLong, s.[Est Size Best], s.[Est Size Max], 
             s.[Est Size Min], s.Acoustics, s.[Est ID], s.[Actual ID], s.AltSighting, s.AltVessel, s.Angle, s.Bearing, s.CloseApproachCount, s.[D units], s.Depth, s.DOT, s.[Frames 1], s.[Frames 2], s.[Frames 3], s.GEX, s.GEY, s.[Group Beh], s.[Group Type], s.Heading, s.Height, s.Height1, s.[Loc Code], 
             s.LocDesc, s.[Num Calves], s.Obs, s.Obs1, s.[Other Beh 1], s.[Other Beh 2], s.[Other Beh 3], s.Permit, s.[Photographer 1], s.[Photographer 2], s.[Photographer 3], s.[Photos?], s.[Position Type], s.PreyType, s.Range, s.RangeSource, s.RangeSource1, s.Reticle, s.Reticle1, 
             s.[Roll/File Number 1], s.[Roll/File Number 2], s.[Roll/File Number 3], s.Scattering, s.[Series Number 1], s.[Series Number 2], s.[Series Number 3], s.[Sight Type], s.Temp, s.[Total Samples], s.[Total Tags], s.Comments, s.SourceDB, s.RG_hash, s.Vessel_hash, s.Sighting_hash, s.DailyEffortID, 
             se.SightEvent, o.Species AS OtherSpecies, sa.[Sample Type]
FROM   dbo.SightingT AS s LEFT OUTER JOIN
             dbo.OtherSpeciesT AS o ON s.[Research Group] = o.[Research Group] AND s.Vessel = o.Vessel AND s.Date = o.Date AND s.Sighting = o.Sighting LEFT OUTER JOIN
             dbo.SightingEventT AS se ON s.[Research Group] = se.[Research Group] AND s.Vessel = se.Vessel AND s.Date = se.Date AND s.Sighting = se.Sighting LEFT OUTER JOIN
             dbo.SampleT AS sa ON s.[Research Group] = sa.[Research Group] AND s.Vessel = sa.Vessel AND s.Date = sa.Date AND s.Sighting = sa.Sighting LEFT OUTER JOIN
             dbo.SightingIdentificationT AS si ON s.[Research Group] = si.[Research Group] AND s.Vessel = si.Vessel AND s.Date = si.SightingDate AND s.Sighting = si.Sighting
GO

-- dbo.SpeciesSummaryByEffortV
CREATE VIEW dbo.SpeciesSummaryBySightingV
AS
SELECT dbo.SightingT.Species, SUM(dbo.SightingT.[Est Size Best]) AS SpeciesCount, dbo.DailyEffortT.DailyEffortID
FROM   dbo.SightingT INNER JOIN
             dbo.DailyEffortT ON dbo.SightingT.[Research Group] = dbo.DailyEffortT.[Research Group] AND dbo.SightingT.Vessel = dbo.DailyEffortT.Vessel AND dbo.SightingT.Date = dbo.DailyEffortT.Date
GROUP BY dbo.SightingT.Species, dbo.DailyEffortT.DailyEffortID
GO

-- dbo.TagSummaryV
CREATE VIEW dbo.TagSummaryV
AS
SELECT ts.TagSummaryID, ts.DailyEffortID, ts.[Research Group], ts.Vessel, ts.Date, ts.Sighting, ts.Attachment, ts.CallTypes, ts.CEE, ts.DataCollected, ts.DeployBodyLoc, ts.DeployDateTime, ts.DeployRxn, ts.DeployTime, ts.DeployType, ts.Descriptions, ts.DiveTypes, ts.[Field ID] AS Field_ID, 
             ts.GPSTrackSource, ts.HoursData, ts.HoursTotal, ts.PlaybackEnd, ts.PlaybackStart, ts.PlaybackType, ts.PreyData, ts.RecoverDateTime, ts.Segments, ts.SonarLogFilename, ts.Tag# AS TagNum, ts.TagDataFilename, ts.TagOffDateTime, ts.TagType, ts.VHFChannel, ts.Video, 
             ts.TagComments, ts.SourceDB, s.[Start Dec Lat], s.[Start Dec Long], e.Launch, e.Locality, s.Species, s.[Est Size Best], ts.Playback, ts.RecoverDate, ts.RecoverTime, ts.TagOffDate, ts.TagOffTime
FROM   dbo.TagSummaryT AS ts LEFT OUTER JOIN
             dbo.DailyEffortT AS e ON ts.DailyEffortID = e.DailyEffortID LEFT OUTER JOIN
             dbo.SightingT AS s ON ts.[Research Group] = s.[Research Group] AND ts.Vessel = s.Vessel AND ts.Date = s.Date AND ts.Sighting = s.Sighting
GO

-- dbo.TrackV
CREATE VIEW dbo.TrackV
AS
SELECT t.TrackID, t.EffortID, t.ResearchGroupID, t.TrackCompleteCodeID, t.VesselID, t.SourceID, t.SurveyDate, t.TrackFileName, t.TrackFileType, t.Useable, t.HitRate, t.TrackFileSize, t.Comments, t.StartTime, t.EndTime, t.GPSPointCount, t.TrackDuration, s.Source, 
             rg.Code AS [Research Group], v.VesselName, v.VesselCode, tc.TrackCompleteCode, CAST(YEAR(t.SurveyDate) AS int) AS EffortYear
FROM   dbo.TrackT AS t LEFT OUTER JOIN
             dbo.SourceT AS s ON t.SourceID = s.SourceID LEFT OUTER JOIN
             dbo.ResearchGroupT AS rg ON t.ResearchGroupID = rg.ResearchGroupID LEFT OUTER JOIN
             dbo.VesselT AS v ON t.VesselID = v.VesselID LEFT OUTER JOIN
             dbo.TrackCompleteCodeT AS tc ON t.TrackCompleteCodeID = tc.TrackCompleteCodeID
GO

