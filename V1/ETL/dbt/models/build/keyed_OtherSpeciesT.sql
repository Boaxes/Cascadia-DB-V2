-- OtherSpeciesT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"OtherSpeciesID\")",
                     "create index on {{ this }} (id)"]) }}
{{ keyed_table('OtherSpeciesT', 'OtherSpeciesID', ['Research Group', 'Vessel', 'Date', 'Sighting', 'Species', 'Count', 'Comments']) }}
