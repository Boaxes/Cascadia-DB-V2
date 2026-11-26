-- A spelling the rule changes a value to is never itself changed again: one
-- pass of the map gives the final spelling.
select a.unit, a.from_value, a.to_value, b.to_value as then_becomes
from {{ ref('spelling_map') }} a
join {{ ref('spelling_map') }} b on b.unit = a.unit and b.from_value = a.to_value and b.to_value <> a.to_value
