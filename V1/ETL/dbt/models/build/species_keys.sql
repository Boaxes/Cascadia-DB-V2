-- Which species a typed species code means, to SpeciesT's SpeciesID: its
-- Abbreviation, or a spelling seeds/species_matches.csv gives another code
-- for (Zc is California sea lion, Zaca). Read as the hash reads it
-- (build.key_text). A typed code loses an observer's trailing question mark
-- before it is looked up here (macros/links.sql, species_join).
with codes as (
    select {{ build_fn() }}.key_text("Abbreviation") as key, "SpeciesID" as id from {{ ref('SpeciesT') }}
)
select distinct on (key) key, id from (
    select key, id, 1 as rank from codes
    union all
    select {{ build_fn() }}.key_text(m.spelling), c.id, 2
    from {{ ref('species_matches') }} m join codes c on c.key = {{ build_fn() }}.key_text(m.code)
) k
where key is not null
order by key, rank, id
