-- TrackCompleteCodeT: DB167's rows, cleaned.
with {{ cleaned_ctes('TrackCompleteCodeT') }}
select {{ column_list('TrackCompleteCodeT', 'c') }} from c
