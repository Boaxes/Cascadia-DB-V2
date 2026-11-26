-- The website's vessel list names each vessel once: spellings of one vessel
-- ("Ruby" and "RUBY", or two texts DB167's VesselT says are one boat) are one
-- row, not several, so filtering by a vessel finds all of its records.
select coalesce('VesselT ' || legacy_vessel_id, 'text ' || lower(code)) as vessel, count(*) as rows
from {{ ref('vessel') }}
group by 1
having count(*) > 1
