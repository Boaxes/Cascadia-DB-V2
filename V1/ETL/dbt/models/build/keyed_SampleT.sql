-- SampleT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"SampleID\")",
                     "create index on {{ this }} (id)"]) }}
-- Besides spelling: a CRC Certainty of Sample ID that is only a
-- number is cleared. A sample's id is made from the Sample Type DB167 has, so
-- merging Sample Type variants never changes it.
{% set overrides = {
    'Certainty of Sample ID': "case when c0.\"Research Group\" = 'CRC' and c0.\"Certainty of Sample ID\" ~ '^[0-9]+$' then null else c0.\"Certainty of Sample ID\" end",
} %}
{{ keyed_table('SampleT', 'SampleID', ['Research Group', 'Vessel', 'Date', 'Sighting', 'Sample #', 'Sample Number', 'Field ID', 'Event', 'Sample Type', 'SampleTime', 'Reaction', 'Comments'], overrides, ['Sample Type']) }}
