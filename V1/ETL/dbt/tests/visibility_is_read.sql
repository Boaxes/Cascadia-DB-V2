-- A visibility written as a number, with or without its leading 0, or as a
-- range, has a visibility in nautical miles. The old pipeline needed a digit
-- before the point, so about 800 readings like .5 were left empty.
select "DailyConditionID", "Visibility (nm)", "Visibility"
from {{ ref('DailyConditionT') }}
where visibility_nm is null
  and (btrim("Visibility (nm)") ~* '^[0-9]*\.?[0-9]+(\s*-\s*[0-9]*\.?[0-9]+)?\s*(nm)?$'
       or btrim("Visibility") ~* '^[0-9]*\.?[0-9]+(\s*-\s*[0-9]*\.?[0-9]+)?\s*(nm)?$')
