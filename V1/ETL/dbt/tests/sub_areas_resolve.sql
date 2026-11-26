-- Every Sub-area an effort records is one of Doug Sandilands's corrected
-- sub-areas, or a spelling his table does not list yet (warns).
{{ config(severity='warn') }}
select distinct e."Sub-area"
from {{ ref('DailyEffortT') }} e
where e."Sub-area" is not null
  and e."Sub-area" not in (select "Corrected Sub-Area" from {{ ref('sub_areas') }})
