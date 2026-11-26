-- Every effort in seeds/removed_efforts.csv has its kept effort in the build,
-- and at least one track names it. Otherwise the row does nothing and should
-- be taken out.
select r.removed_effort, r.kept_effort,
       case when not exists (select 1 from {{ ref('keyed_DailyEffortT') }} e where e."DailyEffortID" = r.kept_effort)
            then 'the kept effort is not in DB167'
            else 'no track names the removed effort' end as problem
from {{ ref('removed_efforts') }} r
where not exists (select 1 from {{ ref('keyed_DailyEffortT') }} e where e."DailyEffortID" = r.kept_effort)
   or not exists (select 1 from {{ source('raw', 'TrackT') }} t where t."EffortID" = r.removed_effort)
