-- IndividualT: the catalogue of known animals, cleaned, with each one's species.
with {{ cleaned_ctes('IndividualT') }}
select {{ column_list('IndividualT', 'c') }},
       sp.id::integer as species_id
from c
left join {{ ref('species_keys') }} sp on sp.key = {{ build_fn() }}.key_text(rtrim(btrim(c."Species"), '?'))
