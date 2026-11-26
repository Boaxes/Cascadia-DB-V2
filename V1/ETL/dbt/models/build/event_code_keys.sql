-- Which day-log code a typed Code means, to EventCodeT's EventCodeID.
select distinct on ({{ build_fn() }}.key_text("EventCode")) {{ build_fn() }}.key_text("EventCode") as key, "EventCodeID" as id
from {{ ref('EventCodeT') }}
where {{ build_fn() }}.key_text("EventCode") is not null
order by {{ build_fn() }}.key_text("EventCode"), "EventCodeID"
