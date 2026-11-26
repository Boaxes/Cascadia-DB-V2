-- TrackT: one GPS track file recorded during an effort, with the website's
-- changes applied, plus its line, status and vessel.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R8  track comments carry <br> tags and an auto-generated statistics
--          block. The tags are stripped, the text kept.
--    It also gains a record for every file in DB167's file list that no track
--    record names, because without one the bucket and the database would
--    disagree about which files exist. They are numbered on from the highest
--    TrackID, in file-name order, as the old import did, and their date and
--    vessel read from the file name. "The highest TrackID" leaves out the
--    six records that name a vessel DB167 no longer has, which the old import
--    had already removed (they are deletions in the audit log, applied in r).
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{#- Status, worked out from two facts: is an effort linked, and is the file
    stored (it has a row in raw.track_geometry, which holds every file in the
    bucket). Both are read after the website's edits, so a link or an upload
    made on the website shows here too. The website writes the same status
    when it links or uploads; the rebuild works it out again rather than
    trusting what was written. -#}
{% set status %}
    case when s."EffortID" is not null and g.object_key is not null then 'available'
         when s."EffortID" is not null then 'missing_file'
         when g.object_key is not null then 'unassociated'
         else 'unresolved' end
{% endset %}

{#- The vessel: its text, ignoring case, and otherwise DB167's own VesselID,
    or the one the website set (macros/lists.sql, vessel_id). -#}
{% set vessel %}
    case when s.__edits ? 'vessel_id' then vessel_edited.same_as
         else coalesce(vessel_by_text.same_as,
                       (select min(l.same_as) from {{ ref('vessel_for_text') }} l
                        where l.legacy_vessel_id = s."VesselID")) end
{% endset %}

with kept as (
    select t.* from {{ source('raw', 'TrackT') }} t
    where not (t."VesselID" is not null
               and not exists (select 1 from {{ source('raw', 'VesselT') }} v where v."VesselID" = t."VesselID"))
),
unnamed_files as (
    select f.* from {{ source('raw', 'TrackFileList') }} f
    where not exists (select 1 from kept k
                      where lower(btrim(cast(k."TrackFileName" as text))) = lower(btrim(f."FileName")))
),
cleaned as (
    select
        t."TrackID" as "TrackID",
        t."UnifiedDB_DailyEffortID" as "UnifiedDB_DailyEffortID",
        t."ResearchGroupID" as "ResearchGroupID",
        t."TrackCompleteCodeID" as "TrackCompleteCodeID",
        t."VesselID" as "VesselID",
        t."SourceID" as "SourceID",
        t."SurveyDate" as "SurveyDate",
        t."TrackFileName" as "TrackFileName",
        t."TrackFileType" as "TrackFileType",
        t."Useable" as "Useable",
        t."HitRate" as "HitRate",
        t."TrackFileSize" as "TrackFileSize",
        case when t."Comments" ~ '<[^>]*>' then btrim(regexp_replace(t."Comments", '<[^>]*>', ' ', 'g')) else t."Comments" end as "Comments",
        t."StartTime" as "StartTime",
        t."EndTime" as "EndTime",
        t."GPSPointCount" as "GPSPointCount",
        t."TrackDuration" as "TrackDuration",
        t."EffortID" as "EffortID",
        t."Research Group" as "Research Group",
        t."Vessel" as "Vessel"
    from {{ source('raw', 'TrackT') }} t

    union all

    select
        ((select max("TrackID") from kept) + row_number() over (order by f."FileName"))::integer as "TrackID",
        null::integer as "UnifiedDB_DailyEffortID",
        null::integer as "ResearchGroupID",
        null::integer as "TrackCompleteCodeID",
        null::integer as "VesselID",
        null::integer as "SourceID",
        (case when btrim(f."FileName") ~ '^[0-9]{8}'
                     then to_date(left(btrim(f."FileName"), 8), 'YYYYMMDD') end)::date as "SurveyDate",
        btrim(f."FileName") as "TrackFileName",
        'csv'::text as "TrackFileType",
        true as "Useable",
        null::text as "HitRate",
        null::text as "TrackFileSize",
        null::text as "Comments",
        null::timestamp without time zone as "StartTime",
        null::timestamp without time zone as "EndTime",
        null::double precision as "GPSPointCount",
        null::double precision as "TrackDuration",
        null::integer as "EffortID",
        null::text as "Research Group",
        {{ vessel_in_file_name('f."FileName"') }} as "Vessel"
    from unnamed_files f
),
r as (
    {{ replay_rows('cleaned', 'TrackT', 'TrackID') }}
),
s as (
    select {{ replayed_columns('TrackT', 'r') }}, r.__edits,
           btrim(cast(r."TrackFileName" as text)) as __file_as_imported
    from r
),
named as (
    select s.*, {{ edited('file_name', 's.__file_as_imported', 'text', 's.__edits') }} as __file_name
    from s
)
select
    {{ column_list('TrackT', 's') }},
    -- The line comes from the file itself, one row per file in the bucket
    -- (raw.track_geometry). Records naming the same file share its line.
    g.geom::geometry(MultiLineString,4326) as geom,
    g.length_nm::numeric(12,3) as length_nm,
    g.point_count::integer as point_count,
    {{ status }} as track_status,
    s.__file_name as file_name,
    {{ vessel }} as vessel_id
from named s
left join {{ source('raw', 'track_geometry') }} g on lower(g.object_key) = lower(s.__file_name)
{{ vessel_joins('s') }}
