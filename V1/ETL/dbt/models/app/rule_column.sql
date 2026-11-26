-- Which rule changed which column, for the history window on a record's page
-- (Django/survey/history.py). One row per rule and column.
{{ config(materialized='table') }}
with spelling as (
    select distinct 'Spelling'::text as rule_id,
           'Spelling made consistent: values that differ only in capitals or spaces, clear typos and listed '
           || 'synonyms become one spelling.'::text as description, table_name as target_table, column_name
    from {{ ref('value_changes') }} where kind in ('capitals', 'spaces', 'typo', 'synonym')
    union all
    select distinct 'Sub-area', 'Sub-area corrected to Doug Sandilands''s table of sub-areas.', table_name, column_name
    from {{ ref('value_changes') }} where kind = 'corrected'
    union all
    select distinct 'Trim', 'Spaces at the start and end removed.', table_name, column_name
    from {{ ref('value_changes') }} where kind = 'trim'
    union all
    select distinct 'Empty', 'Empty text made NULL.', table_name, column_name
    from {{ ref('value_changes') }} where kind = 'empty'
),
other (rule_id, description, target_table, column_name) as (
    values
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared.',
     'SightingT', 'Start Dec Lat'),
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared.',
     'SightingT', 'Start Dec Long'),
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared. So is a CRC end position whose longitude is past 180.',
     'SightingT', 'End Dec Lat'),
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared. So is a CRC end position whose longitude is past 180.',
     'SightingT', 'End Dec Long'),
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared.',
     'DailyEventT', 'Dec Lat'),
    ('Position', 'A position of exactly (0, 0) was not recorded, and both halves are cleared.',
     'DailyEventT', 'Dec Long'),
    ('Beaufort', 'CRC: the Beaufort scale runs 0 to 12; anything else is cleared.', 'DailyConditionT', 'Beaufort'),
    ('Quality', 'CRC: valid codes are E, G, VG, F and P; anything else is cleared.', 'DailyConditionT', 'Quality'),
    ('Certainty', 'CRC: a Certainty of Sample ID that is only a number is cleared.', 'SampleT', 'Certainty of Sample ID'),
    ('Comments', 'HTML tags DB167 stores in track comments are removed.', 'TrackT', 'Comments')
)
select * from spelling
union all
select * from other
