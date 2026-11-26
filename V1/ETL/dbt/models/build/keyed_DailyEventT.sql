-- DailyEventT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"DailyEventID\")",
                     "create index on {{ this }} (id)"]) }}
-- Besides spelling: a position of exactly (0, 0) was not recorded,
-- and is cleared.
{% set overrides = {
    'Dec Lat': "case when c0.\"Dec Lat\" = 0 and c0.\"Dec Long\" = 0 then null else c0.\"Dec Lat\" end",
    'Dec Long': "case when c0.\"Dec Lat\" = 0 and c0.\"Dec Long\" = 0 then null else c0.\"Dec Long\" end",
} %}
{{ keyed_table('DailyEventT', 'DailyEventID', ['Research Group', 'Vessel', 'Date', 'EventDateTime', 'Code'], overrides) }}
