-- SightingT: sightings, with the hashed Primary Key, the website's edits, and
-- Foreign Keys to the effort (by Research Group, Vessel and Date), research
-- group, vessel and species. The calculated columns:
--   identified_individual_count  individual animals identified, from IdentificationT
--   geom, end_geom               start and end positions
--   num_calves                   Num Calves when it is a whole number (1? is not)
--   depth_m                      Depth in metres, where its unit is m, ft or fm
--   species_uncertain            the observer ended the species with a question mark
-- A value the website set for species_id, num_calves or depth_m wins over the
-- worked out one; a species_id that names no species is left NULL.
{%- set num_calves %}
    case when s."Num Calves" ~ '^\s*[0-9]+\s*$' then btrim(s."Num Calves")::integer end
{%- endset %}
{%- set depth_m %}
    case when lower(btrim(s."D units")) in ('m', 'meters', 'metres') then round(s."Depth"::numeric, 2)
         when lower(btrim(s."D units")) in ('ft', 'feet') then round((s."Depth" * 0.3048)::numeric, 2)
         when lower(btrim(s."D units")) = 'fm' then round((s."Depth" * 1.8288)::numeric, 2)
    end
{%- endset %}
with {{ replayed('SightingT') }},
identified as (
    select sighting_id, count(distinct "IndividualID") as n
    from {{ ref('IdentificationT') }}
    where sighting_id is not null and "IndividualID" is not null
    group by 1
)
select s.id, {{ column_list('SightingT', 's') }},
       {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id,
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       {{ edited_reference('species_id', 'sp.id', 'SpeciesT') }} as species_id,
       coalesce(i.n, 0)::integer as identified_individual_count,
       {{ adapter.quote(this.schema) }}.point_from(s."Start Dec Lat", s."Start Dec Long") as geom,
       {{ adapter.quote(this.schema) }}.point_from(s."End Dec Lat", s."End Dec Long") as end_geom,
       {{ edited('num_calves', num_calves, 'integer', 's.__edits') }} as num_calves,
       {{ edited('depth_m', depth_m, 'numeric(10,2)', 's.__edits') }} as depth_m,
       coalesce(btrim(s."Species") like '%?', false) as species_uncertain
from s
left join lateral {{ parent_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's.__effort', 's."DailyEffortID"') }} effort on true
left join identified i on i.sighting_id = s.id
{{ species_join('s') }}
{{ group_and_vessel_joins('s') }}
