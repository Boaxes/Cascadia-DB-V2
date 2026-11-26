-- DB167's SightingV: each sighting with its sighting events, other species and
-- samples, one row per combination, found by their Foreign Key sighting_id.
select {%- for c in raw_column_names('SightingT') %} s.{{ adapter.quote(c) }},{% endfor %}
       se."SightEvent", o."Species" as "OtherSpecies", sa."Sample Type"
from {{ ref('SightingT') }} s
left join {{ ref('OtherSpeciesT') }} o on o.sighting_id = s.id
left join {{ ref('SightingEventT') }} se on se.sighting_id = s.id
left join {{ ref('SampleT') }} sa on sa.sighting_id = s.id
