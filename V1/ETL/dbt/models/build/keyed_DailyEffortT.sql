-- DailyEffortT, cleaned, with its hashed Primary Key (macros/keys.sql).
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"DailyEffortID\")",
                     "create index on {{ this }} (id)"]) }}
{{ keyed_table('DailyEffortT', 'DailyEffortID', ['Research Group', 'Vessel', 'Date']) }}
