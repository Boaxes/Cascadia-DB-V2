-- VesselListT: the vessel list. raw.vessel_list keeps every vessel's id for good.
--
-- One row per vessel text, carrying DB167's VesselT code and name where the
-- text matches either of them, ignoring case (lowest VesselID first: VesselT
-- has three rows for MIG and two for MOK). A vessel text any table uses that
-- the list has no spelling of, in any case, is given the next id, in text
-- order; swapping the build in saves it there, so the next build gives it the
-- same id (macros/lists.sql).
--
-- The texts come straight from raw, from every table that records a vessel,
-- and from the names of the track files DB167 has no track record for: no
-- cleaning step or edit touches a vessel's text. Which id a record gets is
-- models/dbo/lookups/vessel_for_text.sql.
with known as (
    select * from {{ source('raw', 'vessel_list') }}
),
used as (
    {%- for table in ['DailyEffortT', 'SightingT', 'DailyConditionT', 'DailyEventT', 'SampleT', 'TagSummaryT',
                      'TrackingT', 'SightingEventT', 'OtherSpeciesT', 'IdentificationT', 'SightingIdentificationT', 'TrackT'] %}
    select btrim("Vessel") as vessel_text from {{ source('raw', table) }} union all
    {%- endfor %}
    select {{ vessel_in_file_name('"FileName"') }} from {{ source('raw', 'TrackFileList') }}
),
spellings as (
    -- One spelling of each text not yet in the list, the alphabetically first.
    select min(vessel_text) as vessel_text
    from used
    where vessel_text <> ''
      and lower(vessel_text) not in (select lower(btrim(vessel_text)) from known)
    group by lower(vessel_text)
),
new as (
    select u.vessel_text,
           (select coalesce(max(vessel_id), 0) from known) + row_number() over (order by u.vessel_text) as vessel_id,
           v."VesselCode" as code, v."VesselName" as name, v."VesselID" as legacy_vessel_id
    from spellings u
    left join lateral (
        select "VesselCode", "VesselName", "VesselID" from {{ source('raw', 'VesselT') }}
        where lower(btrim("VesselCode")) = lower(u.vessel_text)
           or lower(btrim("VesselName")) = lower(u.vessel_text)
        order by "VesselID" limit 1
    ) v on true
)
select vessel_id::integer         as vessel_id,
       vessel_text::text          as vessel_text,
       code::text                 as code,
       name::text                 as name,
       legacy_vessel_id::integer  as legacy_vessel_id
from known
union all
select vessel_id::integer, vessel_text::text, code::text, name::text, legacy_vessel_id::integer
from new
