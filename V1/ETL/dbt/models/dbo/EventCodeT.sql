-- EventCodeT: DB167's day-log codes, plus every code the day log uses that it
-- lacks, ignoring case and spaces, with no description and an EventCodeID
-- above the highest, in code order. name is the short display name the
-- website shows (seeds/event_code_names.csv).
with {{ cleaned_ctes('EventCodeT') }},
missing as (
    select distinct on ({{ build_fn() }}.key_text("Code")) btrim("Code") as code
    from {{ ref('keyed_DailyEventT') }}
    where {{ build_fn() }}.key_text("Code") is not null
      and {{ build_fn() }}.key_text("Code") not in
          (select {{ build_fn() }}.key_text("EventCode") from c where "EventCode" is not null)
    order by {{ build_fn() }}.key_text("Code"), "Code" collate "C"
),
codes as (
    select {{ column_list('EventCodeT', 'c') }} from c
    union all
    select ((select max("EventCodeID") from c) + row_number() over (order by code collate "C"))::integer,
           code, null::text, null::integer
    from missing
)
select codes.*, n.name
from codes
left join {{ ref('event_code_names') }} n on {{ build_fn() }}.key_text(n.code) = {{ build_fn() }}.key_text(codes."EventCode")
