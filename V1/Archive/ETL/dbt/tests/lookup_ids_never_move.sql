-- An id in the species or vessel list is given once and never changes: every
-- row the list in raw holds is in dbo with the same id and the same code.
select 'species' as list, s.species_id as id from {{ source('raw', 'species') }} s
left join {{ ref('SpeciesT') }} d on d.species_id = s.species_id and d.code = s.code
where d.species_id is null
union all
select 'vessel', v.vessel_id from {{ source('raw', 'vessel_list') }} v
left join {{ ref('VesselListT') }} d on d.vessel_id = v.vessel_id and d.vessel_text = v.vessel_text
where d.vessel_id is null
