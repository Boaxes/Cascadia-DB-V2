-- SightingEventT, cleaned, with its hashed Primary Key (macros/keys.sql). The
-- time is EventTime: EventDateTime, which DB167 added in 2026, is only Date and
-- EventTime together.
{{ config(post_hook=["create index on {{ this }} (__natural)", "create index on {{ this }} (\"SightingEventID\")",
                     "create index on {{ this }} (id)"]) }}
{{ keyed_table('SightingEventT', 'SightingEventID', ['Research Group', 'Vessel', 'Date', 'Sighting', 'EventTime', 'SightEvent', 'Field ID', 'EventID', 'Reaction', 'SightEventComments', 'Dec Lat', 'Dec Long']) }}
