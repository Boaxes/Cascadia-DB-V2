-- IdentificationT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"IdentificationID\")",
                     "create index on {{ this }} (id)"]) }}
{{ keyed_table('IdentificationT', 'IdentificationID', ['Research Group', 'Vessel', 'Date', 'Sighting', 'IndividualID', 'Field ID']) }}
