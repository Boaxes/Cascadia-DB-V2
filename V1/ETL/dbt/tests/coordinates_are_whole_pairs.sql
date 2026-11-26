-- A coordinate pair is either a position -- both halves, neither 0 -- or
-- empty (R7). The old pipeline cleared only exact (0,0) pairs, and half pairs
-- only for CRC sighting starts, so 86 sightings ended on the equator.
{%- set pairs = [('SightingT', 'SightingID', 'Start Dec Lat', 'Start Dec Long'),
                 ('SightingT', 'SightingID', 'End Dec Lat', 'End Dec Long'),
                 ('DailyEventT', 'DailyEventID', 'Dec Lat', 'Dec Long'),
                 ('DailyConditionT', 'DailyConditionID', 'Dec Lat', 'Dec Long')] %}
{%- for table, key, lat, lon in pairs %}
{{ 'union all' if not loop.first }}
select '{{ table }}' as table_name, "{{ key }}" as id, '{{ lat }}' as latitude
from {{ ref(table) }}
where not (("{{ lat }}" is null and "{{ lon }}" is null)
           or ("{{ lat }}" is not null and "{{ lon }}" is not null and "{{ lat }}" <> 0 and "{{ lon }}" <> 0))
{%- endfor %}
