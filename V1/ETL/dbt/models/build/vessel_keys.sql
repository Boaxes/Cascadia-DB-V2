-- Which vessel a typed vessel text means, read as the hash reads it: a
-- VesselT code first, then a VesselT name ('Truth' is TRH), then the text as
-- its own vessel.
with v as (select vessel_key, vessel_id from {{ ref('vessels') }})
select distinct on (key) key, vessel_id from (
    select substring(vessel_key from 6) as key, vessel_id, 1 as rank from v where vessel_key like 'code:%'
    union all
    select k."VesselName", v.vessel_id, 2
    from (select {{ build_fn() }}.key_text("VesselName") as "VesselName", 'code:' || {{ build_fn() }}.key_text("VesselCode") as vessel_key,
                 "VesselID"
          from {{ source('raw', 'VesselT') }}) k
    join v on v.vessel_key = k.vessel_key
    where k."VesselName" is not null
    union all
    select substring(vessel_key from 6), vessel_id, 3 from v where vessel_key like 'text:%'
) keys
order by key, rank, vessel_id
