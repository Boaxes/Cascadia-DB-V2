-- Every sighting and sample whose species names one species is filed under
-- it. A value naming more than one, like Bm/Bp, has no species by design.
{%- for table, key in [('SightingT', 'SightingID'), ('SampleT', 'SampleID')] %}
{{ 'union all' if not loop.first }}
select '{{ table }}' as table_name, "{{ key }}" as id, "Species" from {{ ref(table) }}
where species_id is null
  and btrim(coalesce("Species", '')) <> ''
  and btrim(rtrim(btrim("Species"), '?')) <> ''
  and btrim("Species") !~ '[/,]'
{%- endfor %}
