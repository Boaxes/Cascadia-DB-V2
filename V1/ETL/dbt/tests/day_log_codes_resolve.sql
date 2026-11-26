-- Every day-log entry with a code has its Foreign Key to EventCodeT (rule 9).
select id, "DailyEventID", "Code" from {{ ref('DailyEventT') }}
where "Code" is not null and event_code_id is null
