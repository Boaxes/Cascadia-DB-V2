-- Which research group a typed Research Group means: its code, read as the
-- hash reads it (build.key_text), to ResearchGroupT's ResearchGroupID.
select distinct on ({{ build_fn() }}.key_text("Code")) {{ build_fn() }}.key_text("Code") as key, "ResearchGroupID" as id
from {{ ref('ResearchGroupT') }}
where {{ build_fn() }}.key_text("Code") is not null
order by {{ build_fn() }}.key_text("Code"), "ResearchGroupID"
