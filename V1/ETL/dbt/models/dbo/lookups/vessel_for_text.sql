-- Which vessel each vessel-list row stands for, and so which vessel a
-- record's vessel text means, ignoring case.
--
-- The vessel list keeps a row for every spelling it has ever met, and each
-- keeps its id for good. Spellings of one vessel are one vessel: "Ruby" and
-- "RUBY", which differ only in case, or "CTS" and "CetusSpecula", which
-- DB167's VesselT says are the same boat. Every record of a vessel gets one
-- id, same_as: the id of the spelling most records use, ties going to the
-- lowest id. An id the website stored on a record is read through the same
-- mapping (macros/lists.sql, vessel_id).
--
--   vessel_id         the list row
--   text_key          its text, trimmed and in lower case
--   first_of_text     the lowest id with that text_key: a record's text is
--                     matched to this row
--   legacy_vessel_id  DB167's VesselID, where known
--   same_as           the id that stands for the vessel
with list as (
    select vessel_id, lower(btrim(vessel_text)) as text_key, btrim(vessel_text) as vessel_text, legacy_vessel_id
    from {{ ref('VesselListT') }}
),
grouped as (
    -- A text's vessel: its VesselT where the list knows one for any of the
    -- text's spellings, otherwise the text itself.
    select l.*,
           coalesce('VesselT ' || (select min(k.legacy_vessel_id) from list k where k.text_key = l.text_key),
                    'text ' || l.text_key) as vessel
    from list l
),
used as (
    select vessel_text, count(*) as records from (
        {%- for table in ['DailyEffortT', 'SightingT', 'DailyConditionT', 'DailyEventT', 'SampleT', 'TagSummaryT',
                          'TrackingT', 'SightingEventT', 'OtherSpeciesT', 'IdentificationT', 'SightingIdentificationT', 'TrackT'] %}
        select btrim("Vessel") as vessel_text from {{ source('raw', table) }}{{ ' union all' if not loop.last }}
        {%- endfor %}
    ) texts
    group by 1
)
select g.vessel_id, g.text_key,
       g.vessel_id = min(g.vessel_id) over (partition by g.text_key) as first_of_text,
       g.legacy_vessel_id,
       first_value(g.vessel_id) over (partition by g.vessel
                                      order by coalesce(u.records, 0) desc, g.vessel_id) as same_as
from grouped g
left join used u on u.vessel_text = g.vessel_text
