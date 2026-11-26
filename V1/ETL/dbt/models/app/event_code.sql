-- Names of the day-log codes, including those added to EventCodeT.
select "EventCodeID" as id, "EventCode" as code, name, "CodeDescription" as description, "SortOrder" as sort_order
from {{ ref('EventCodeT') }} c
