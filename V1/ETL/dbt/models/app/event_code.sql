-- What a daily event's code means. DB167's EventCodeT, plus a short name.
{{ config(materialized='updatable_view') }}
SELECT c."EventCodeID"     AS id,
       c."EventCode"       AS code,
       c.name,
       c."CodeDescription" AS description,
       c."SortOrder"       AS sort_order
FROM   {{ ref('EventCodeT') }} c
