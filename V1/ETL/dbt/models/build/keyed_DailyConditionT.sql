-- DailyConditionT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"DailyConditionID\")",
                     "create index on {{ this }} (id)"]) }}
-- Besides spelling: CRC's Beaufort outside 0 to 12 and Quality other
-- than E, G, VG, F and P are cleared.
{% set overrides = {
    'Beaufort': "case when c0.\"Research Group\" = 'CRC' and (c0.\"Beaufort\" < 0 or c0.\"Beaufort\" > 12) then null else c0.\"Beaufort\" end",
    'Quality': "case when c0.\"Research Group\" = 'CRC' and upper(c0.\"Quality\") not in ('E', 'G', 'VG', 'F', 'P') then null else c0.\"Quality\" end",
} %}
{{ keyed_table('DailyConditionT', 'DailyConditionID', ['Research Group', 'Vessel', 'Date', 'ConditionDateTime'], overrides) }}
