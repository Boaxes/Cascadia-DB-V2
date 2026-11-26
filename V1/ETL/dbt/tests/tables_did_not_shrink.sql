-- depends_on: {{ ref('DailyEffortT') }}
-- depends_on: {{ ref('DailyEventT') }}
-- depends_on: {{ ref('DailyConditionT') }}
-- depends_on: {{ ref('SightingT') }}
-- depends_on: {{ ref('SightingEventT') }}
-- depends_on: {{ ref('OtherSpeciesT') }}
-- depends_on: {{ ref('SampleT') }}
-- depends_on: {{ ref('IdentificationT') }}
-- depends_on: {{ ref('TrackT') }}
-- No main table has far fewer rows in this build than in the live site's dbo
-- (var max_shrink, 5% unless set). A DB167 import that arrives half empty
-- would otherwise be published as if it were a normal day. The website's own
-- deletes are a handful of rows, well inside the margin. The first-time build
-- (replay: false) has none of the website's edits or created tracks yet, so it
-- is not compared. A table the live
-- dbo does not have yet is skipped, and so is a live dbo still in the old
-- structure (no id column): the first build of the new pipeline legitimately
-- drops some rows the old import kept, as the compare with live explains.
{%- set shrink = var('max_shrink', 0.05) %}
with counts as (
{%- for t in ['DailyEffortT', 'DailyEventT', 'DailyConditionT', 'SightingT', 'SightingEventT',
              'OtherSpeciesT', 'SampleT', 'IdentificationT', 'TrackT'] %}
{%- set live = adapter.get_relation(database=target.database, schema='dbo', identifier=t) %}
{%- if live and 'id' in (adapter.get_columns_in_relation(live) | map(attribute='name') | list) %}
    select '{{ t }}'::text as table_name,
           (select count(*) from {{ live }}) as live_rows,
           (select count(*) from {{ ref(t) }}) as new_rows
    union all
{%- endif %}
{%- endfor %}
    select null::text as table_name, 0::bigint as live_rows, 0::bigint as new_rows where false
)
select * from counts
where {{ 'true' if var('replay', true) else 'false' }}
  and new_rows < live_rows * (1 - {{ shrink }})
