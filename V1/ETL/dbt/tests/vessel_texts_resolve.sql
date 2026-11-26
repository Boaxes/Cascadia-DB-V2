-- Every record with vessel text is linked to a vessel.
{%- set tables = ['DailyEffortT', 'DailyConditionT', 'DailyEventT', 'SightingT', 'SampleT', 'TagSummaryT',
                  'TrackingT', 'SightingEventT', 'OtherSpeciesT', 'IdentificationT', 'SightingIdentificationT', 'TrackT'] %}
{%- for t in tables %}
{{ 'union all' if not loop.first }}
select '{{ t }}' as table_name, btrim("Vessel") as vessel_text from {{ ref(t) }}
where btrim(coalesce("Vessel", '')) <> '' and vessel_id is null
{%- endfor %}
