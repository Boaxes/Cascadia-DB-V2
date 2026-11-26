-- One row per vessel, for VesselListT, and which typed vessel text means which
-- vessel (models/build/vessel_keys.sql).
--
-- A vessel is a row of DB167's VesselT (one per code, the lowest VesselID where
-- VesselT repeats a code), or a vessel typed in the data that matches no
-- VesselT code or name, ignoring case and spaces. Its vessel_id is the one
-- app.vessel_number keeps for it; a vessel met for the first time gets the
-- next number, in order of its key, and the swap saves it.
--
--   vessel_key  'code:' and VesselT's code, or 'text:' and the typed text,
--               read as the hash reads it (build.key_text)
with fleet as (
    select distinct on ({{ build_fn() }}.key_text("VesselCode"))
           'code:' || {{ build_fn() }}.key_text("VesselCode") as vessel_key,
           btrim("VesselCode") as code, btrim("VesselName") as name, "VesselID" as legacy_vessel_id
    from {{ source('raw', 'VesselT') }}
    where {{ build_fn() }}.key_text("VesselCode") is not null
    order by {{ build_fn() }}.key_text("VesselCode"), "VesselID"
),
names as (
    select distinct on ({{ build_fn() }}.key_text("VesselName"))
           {{ build_fn() }}.key_text("VesselName") as key, 'code:' || {{ build_fn() }}.key_text("VesselCode") as vessel_key
    from {{ source('raw', 'VesselT') }}
    where {{ build_fn() }}.key_text("VesselName") is not null and {{ build_fn() }}.key_text("VesselCode") is not null
    order by {{ build_fn() }}.key_text("VesselName"), "VesselID"
),
typed as (
    -- Every vessel the data types, as dbo spells it.
    select coalesce(m.to_value, v.value) as spelling, sum(v.records) as records
    from {{ ref('spelling_values') }} v
    left join {{ ref('spelling_map') }} m on m.unit = v.unit and m.from_value = v.value
    where v.unit = 'vessel'
    group by 1
    union all
    select vessel, count(*) from {{ ref('bucket_tracks') }} where vessel is not null group by 1
),
new_typed as (
    select distinct on ({{ build_fn() }}.key_text(spelling))
           'text:' || {{ build_fn() }}.key_text(spelling) as vessel_key, btrim(spelling) as code
    from typed
    where {{ build_fn() }}.key_text(spelling) is not null
      and 'code:' || {{ build_fn() }}.key_text(spelling) not in (select vessel_key from fleet)
      and {{ build_fn() }}.key_text(spelling) not in (select key from names)
    order by {{ build_fn() }}.key_text(spelling), records desc, spelling collate "C"
),
everything as (
    select vessel_key, code, name, legacy_vessel_id from fleet
    union all
    select vessel_key, code, null, null from new_typed
)
select coalesce(n.vessel_id,
                (select coalesce(max(vessel_id), 0) from {{ source('app', 'vessel_number') }})
                + row_number() over (partition by n.vessel_id is null order by e.vessel_key collate "C"))::integer as vessel_id,
       e.vessel_key, e.code, e.name, e.legacy_vessel_id::integer as legacy_vessel_id,
       n.vessel_id is null as is_new
from everything e
left join {{ source('app', 'vessel_number') }} n on n.vessel_key = e.vessel_key
