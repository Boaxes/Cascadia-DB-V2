-- SourceT: DB167's rows, cleaned.
with {{ cleaned_ctes('SourceT') }}
select {{ column_list('SourceT', 'c') }} from c
