-- SightingT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"SightingID\")",
                     "create index on {{ this }} (id)"]) }}
-- Besides spelling: a position of exactly (0, 0) was not recorded,
-- and is cleared, so is a CRC end position whose longitude is past 180, and so
-- is a CRC start position that has a latitude or a longitude but not both.
{% set overrides = {
    'Start Dec Lat': "case when (c0.\"Start Dec Lat\" = 0 and c0.\"Start Dec Long\" = 0) or (c0.\"Research Group\" = 'CRC' and (c0.\"Start Dec Lat\" is null) <> (c0.\"Start Dec Long\" is null)) then null else c0.\"Start Dec Lat\" end",
    'Start Dec Long': "case when (c0.\"Start Dec Lat\" = 0 and c0.\"Start Dec Long\" = 0) or (c0.\"Research Group\" = 'CRC' and (c0.\"Start Dec Lat\" is null) <> (c0.\"Start Dec Long\" is null)) then null else c0.\"Start Dec Long\" end",
    'End Dec Lat': "case when (c0.\"End Dec Lat\" = 0 and c0.\"End Dec Long\" = 0) or (c0.\"Research Group\" = 'CRC' and (c0.\"End Dec Long\" < -180 or c0.\"End Dec Long\" > 180)) then null else c0.\"End Dec Lat\" end",
    'End Dec Long': "case when (c0.\"End Dec Lat\" = 0 and c0.\"End Dec Long\" = 0) or (c0.\"Research Group\" = 'CRC' and (c0.\"End Dec Long\" < -180 or c0.\"End Dec Long\" > 180)) then null else c0.\"End Dec Long\" end",
} %}
{{ keyed_table('SightingT', 'SightingID', ['Research Group', 'Vessel', 'Date', 'Sighting'], overrides) }}
