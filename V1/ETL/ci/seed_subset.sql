-- Step 2 of ops/build-ci-seed.sh: cut the copy of the real data down to a small
-- one that still hangs together. Runs in a scratch database that holds a copy
-- of schema raw, app.audit_log, app.track_geometry, app.vessel_number and
-- Django's own tables (auth_*, django_*). Nothing here touches the source
-- database.
--
-- What is kept:
--   Efforts      every Cascadia Research Collective (CRC) Effort in the three
--                most recent years (2024 on; the site tests are written around
--                2024); every Effort a website edit (app.audit_log) names;
--                every record the pipeline's corrections
--                (ETL/dbt/seeds/record_fixes.csv) and merged Efforts
--                (removed_efforts.csv) refer to, because dbt tests fail if
--                those records are missing; every Effort with more than one
--                track (multi_track_efforts.csv, 31 of them: a site test counts
--                them); and a little of two other groups, because tests look
--                for records of a group other than CRC: AOP's latest year, and
--                eight Efforts of NB (a check of the website's edits uses one)
--   Everything   under those Efforts: Sightings, Daily Conditions, Day-log
--                events, Other Species, Samples, Sighting Events,
--                Identifications, Tag Summaries, and the Effort crew list
--   Tracks       every track of a kept Effort; every track dated in the two
--                recent years that is blank or unmatched; the tracks the
--                website edits name; the track of a merged Effort
--   Lookups      Species, Event Codes, Sources, Track Complete Codes and
--                Individuals complete; Research Groups and Vessels only the
--                ones the kept records use (the full lists hold people's names)
--   Gone         every other table in raw is emptied (people, collaborators,
--                the snapshot copies of Sightings and Efforts, and so on)
--                except the crew list, which a site test reads. The pipeline
--                reads only 18 of the tables
--
-- The tables the load script (ops/build-ci-seed.sh) fills first:
--   ci.fixes       seeds/record_fixes.csv
--   ci.removed     seeds/removed_efforts.csv
--   ci.multi       seeds/multi_track_efforts.csv
--   ci.pick_efforts  the three Efforts with exactly one track that have the
--                  lowest dbo ids in the source (read from the source's dbo):
--                  site tests take "the first Effort with one track" by id, and
--                  the small seed would otherwise have a different first one
--   ci.file_size   name and size in bytes of every file in the folder of real
--                  track files (the local copy of the GPS bucket)
set client_min_messages = warning;
-- raw refuses changes (a trigger on every table); this is the scratch copy.
set session_replication_role = replica;

-- The pipeline's own reading of typed text (build.key_text in
-- ETL/dbt/macros/functions.sql): trimmed, runs of spaces made one, lower case.
create function ci.kt(value text) returns text language sql immutable as $$
    select nullif(lower(regexp_replace(btrim(value, E' \t\r\n\f\v '), '\s+', ' ', 'g')), '')
$$;

-- ------------------------------------------------- every name in the source, before the cut
-- The words taken out of the data (seed_scrub.sql) come from the whole source, not
-- only from the rows that are kept: a photographer's initials may sit in a photo
-- file name of a kept row though the photographer is in a row that is cut.
-- `clean` is true for the columns that hold only people.
create table ci.name_text as
select x, clean from (
    select "Photographer 1" x, true clean from raw."SightingT" union all select "Photographer 2", true from raw."SightingT"
    union all select "Photographer 3", true from raw."SightingT" union all select "Obs1", true from raw."SightingT"
    union all select "Sampled by", true from raw."SampleT" union all select "PhotoDataBy", true from raw."DailyEffortT"
    union all select "ObsL", true from raw."DailyEventT" union all select "ObsR", true from raw."DailyEventT"
    union all select "Rec", true from raw."DailyEventT"
    union all select "CrewName", true from raw."EffortCrewT" union all select "Initials", true from raw."EffortCrewT"
    union all select "FirstName", true from raw."UserT" union all select "LastName", true from raw."UserT"
    union all select "Username", true from raw."UserT" union all select "Collaborator", true from raw."CollaboratorT"
    union all select first_name, true from auth_user union all select last_name, true from auth_user
    union all select username, true from auth_user union all select actor_name, true from app.audit_log
    union all select "Personnel", false from raw."DailyEffortT"
) t where x is not null;

-- ---------------------------------------------------------------- Efforts
-- Efforts a website edit names that the source itself does not have (an upload
-- for an Effort DB167 does not hold). They stay as they are: nothing to keep.
create table ci.audit_effort_not_in_source as
select distinct (changes -> 'EffortID' ->> 'new')::integer as effort from app.audit_log
where changes ? 'EffortID' and changes -> 'EffortID' ->> 'new' is not null
  and (changes -> 'EffortID' ->> 'new')::integer not in (select "DailyEffortID" from raw."DailyEffortT");

-- Research Group codes the data types that the source's own lookup lacks (DB167
-- has hundreds; the pipeline adds them in dbo).
create table ci.group_not_in_source_lookup as
select distinct ci.kt(g) as code from (select "Research Group" g from raw."DailyEffortT" union select "Research Group" from raw."SightingT") x
where ci.kt(g) is not null and ci.kt(g) not in (select ci.kt("Code") from raw."ResearchGroupT");

create table ci.effort (id integer primary key, why text);

insert into ci.effort
select "DailyEffortID", 'CRC, the three most recent years' from raw."DailyEffortT"
where "Research Group" = 'CRC'
  and extract(year from "Date") >= (select max(extract(year from "Date")) - 2
                                    from raw."DailyEffortT" where "Research Group" = 'CRC')
on conflict do nothing;

-- Another group, so that "other groups" exist (its latest year), and eight
-- Efforts of a third (its latest ones).
insert into ci.effort
select "DailyEffortID", 'AOP, its latest year' from raw."DailyEffortT"
where "Research Group" = 'AOP'
  and extract(year from "Date") = (select max(extract(year from "Date")) from raw."DailyEffortT" where "Research Group" = 'AOP')
on conflict do nothing;
insert into ci.effort
select "DailyEffortID", 'NB, eight Efforts' from raw."DailyEffortT"
where "DailyEffortID" in (select "DailyEffortID" from raw."DailyEffortT" where "Research Group" = 'NB'
                          order by "Date" desc, "DailyEffortID" desc limit 8)
on conflict do nothing;

insert into ci.effort
select "DailyEffortID", 'named by a website edit' from raw."DailyEffortT"
where "DailyEffortID" in (select (changes -> 'EffortID' ->> 'new')::integer from app.audit_log
                          where changes ? 'EffortID' and changes -> 'EffortID' ->> 'new' is not null)
on conflict do nothing;

insert into ci.effort
select s."DailyEffortID", 'holds a Sighting a website edit names' from raw."SightingT" s
where s."SightingID"::text in (select legacy_pk from app.audit_log where target_table = 'SightingT' and legacy_pk is not null)
  and s."DailyEffortID" is not null
on conflict do nothing;

insert into ci.effort
select "DailyEffortID", 'a record fix needs it' from raw."DailyEffortT"
where "DailyEffortID"::text in (select legacy_id from ci.fixes where table_name = 'DailyEffortT')
on conflict do nothing;

insert into ci.effort
select s."DailyEffortID", 'holds a Sighting a record fix needs' from raw."SightingT" s
where s."SightingID"::text in (select legacy_id from ci.fixes where table_name = 'SightingT')
  and s."DailyEffortID" is not null
on conflict do nothing;

insert into ci.effort
select "DailyEffortID", 'the Effort a merged Effort was kept as' from raw."DailyEffortT"
where "DailyEffortID" in (select kept_effort from ci.removed)
on conflict do nothing;

-- The Efforts the site tests pick first (see ci.pick_efforts above).
insert into ci.effort
select "DailyEffortID", 'the first with one track, which site tests pick' from raw."DailyEffortT"
where "DailyEffortID" in (select id from ci.pick_efforts)
on conflict do nothing;

-- Every Effort that has more than one track (a site test counts all 31).
insert into ci.effort
select effort, 'one of the Efforts with several tracks' from ci.multi
where effort in (select "DailyEffortID" from raw."DailyEffortT")
on conflict do nothing;

-- ------------------------------------------------------------- Sightings
create table ci.sighting (id integer primary key);
insert into ci.sighting select "SightingID" from raw."SightingT" where "DailyEffortID" in (select id from ci.effort);

-- ---------------------------------------------------------------- Tracks
create table ci.track (id integer primary key, why text);
insert into ci.track
select "TrackID", 'on a kept Effort' from raw."TrackT" where "EffortID" in (select id from ci.effort)
on conflict do nothing;
-- Dated in the three recent years and blank or unmatched (an EffortID that names
-- an Effort outside the cut is left out: that would be an orphan).
insert into ci.track
select "TrackID", 'recent, unmatched' from raw."TrackT"
where "EffortID" is null
  and extract(year from "SurveyDate") >= (select max(extract(year from "Date")) - 2
                                          from raw."DailyEffortT" where "Research Group" = 'CRC')
on conflict do nothing;
insert into ci.track
select "TrackID", 'named by a website edit' from raw."TrackT"
where "TrackID"::text in (select target_pk from app.audit_log where target_table = 'TrackT')
on conflict do nothing;
insert into ci.track
select "TrackID", 'names a merged Effort' from raw."TrackT"
where "EffortID" in (select removed_effort from ci.removed)
on conflict do nothing;


-- ----------------------------------------------------- Which track files ship
-- About 25 real files, small ones, each kind of track represented:
--   the files of the Efforts the site tests pick first, and of the first three
--     Efforts with several tracks (the tests use those; without their lines the
--     tracks would be "blank" and the tests would find no stored file)
--   the first Effort with several different files (a site test reads its first
--     track's points), and two 2024 July to September Efforts (the export tests
--     ask for exactly those and need a track line among them)
--   4 of the files the website edits matched to Efforts (DB167 had no match)
--   2 of the files the website created tracks for
--   5 of the files of tracks DB167 itself matched, on Efforts from 2024 on (the
--     site tests look at 2024: some are "available" without any website edit)
--   2 files no track names (unmatched, with a line)
-- A file that is not in the folder cannot ship; its track stays, blank.
create table ci.track_files (name text primary key, why text);

insert into ci.track_files
select distinct z.name, 'of an Effort the site tests pick first' from ci.file_size z
join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
where t."EffortID" in (select id from ci.pick_efforts)
on conflict do nothing;

insert into ci.track_files
select distinct z.name, 'of one of the first Efforts with several tracks' from ci.file_size z
join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
where t."EffortID" in (select effort from ci.multi order by effort limit 3)
on conflict do nothing;

insert into ci.track_files
select distinct z.name, 'of the first Effort with several different files' from ci.file_size z
join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
where t."EffortID" = (select t2."EffortID" from raw."TrackT" t2
                      where t2."EffortID" in (select effort from ci.multi)
                      group by t2."EffortID" having count(distinct lower(btrim(t2."TrackFileName"))) > 1
                      order by t2."EffortID" limit 1)
on conflict do nothing;

insert into ci.track_files
select f.name, 'of a July to September 2024 Effort' from (
    select z.name, z.bytes from ci.file_size z
    join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
    join raw."DailyEffortT" e on e."DailyEffortID" = t."EffortID"
    where e."Research Group" = 'CRC' and extract(year from e."Date") = 2024 and extract(month from e."Date") in (7, 8, 9)
      and e."DailyEffortID" in (select "EffortID" from raw."TrackT" where "EffortID" is not null group by 1 having count(*) = 1)
    order by z.bytes, z.name limit 2) f
on conflict do nothing;

insert into ci.track_files
select f.name, 'matched by a website edit' from (
    select z.name, z.bytes from ci.file_size z
    join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
    where t."TrackID"::text in (select target_pk from app.audit_log where target_table = 'TrackT' and action = 'associate')
    order by z.bytes, z.name limit 4) f
on conflict do nothing;

insert into ci.track_files
select f.name, 'created by a website edit' from (
    select z.name, z.bytes from ci.file_size z
    where lower(z.name) in (select lower(btrim(changes -> 'TrackFileName' ->> 'new')) from app.audit_log
                            where target_table = 'TrackT' and action = 'create')
    order by z.bytes, z.name limit 2) f
on conflict do nothing;

insert into ci.track_files
select f.name, 'matched by DB167, 2024 on' from (
    select distinct z.name, z.bytes from ci.file_size z
    join raw."TrackT" t on lower(btrim(t."TrackFileName")) = lower(z.name)
    join raw."DailyEffortT" e on e."DailyEffortID" = t."EffortID"
    where e."DailyEffortID" in (select id from ci.effort)
      and extract(year from e."Date") >= (select max(extract(year from "Date")) - 2 from raw."DailyEffortT" where "Research Group" = 'CRC')
      and lower(z.name) not in (select lower(name) from ci.track_files)
    order by z.bytes, z.name limit 5) f
on conflict do nothing;

insert into ci.track_files
select f.name, 'no track names it' from (
    select z.name, z.bytes from ci.file_size z
    join app.track_geometry g on lower(btrim(g.object_key)) = lower(z.name)
    where g.track_id is not null
    order by z.bytes, z.name limit 2) f
on conflict do nothing;

-- ---------------------------------------------------------- Delete the rest
delete from raw."DailyEffortT"  where "DailyEffortID" not in (select id from ci.effort);
delete from raw."SightingT"     where "SightingID" not in (select id from ci.sighting);
delete from raw."DailyConditionT" where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."DailyEventT"   where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."OtherSpeciesT" where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."TagSummaryT"   where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."SightingEventT" where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."SampleT"       where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."IdentificationT" where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);
delete from raw."TrackT"        where "TrackID" not in (select id from ci.track);
delete from raw."EffortCrewT"   where "DailyEffortID" is null or "DailyEffortID" not in (select id from ci.effort);

-- A child whose parent Sighting was not kept (it could not be: the Effort is the
-- same) would be an orphan the cut made. Checked in seed_checks.sql, not fixed here.

-- Lookups that hold people's names: only what the kept records use.
create table ci.vessel_text (t text primary key);
insert into ci.vessel_text
select distinct ci.kt(v) from (
    select "Vessel" v from raw."DailyEffortT" union all select "Vessel" from raw."SightingT"
    union all select "AltVessel" from raw."SightingT" union all select "Vessel" from raw."DailyConditionT"
    union all select "Vessel" from raw."DailyEventT" union all select "Vessel" from raw."OtherSpeciesT"
    union all select "Vessel" from raw."SampleT" union all select "Vessel" from raw."SightingEventT"
    union all select "Vessel" from raw."IdentificationT" union all select "Vessel" from raw."TagSummaryT"
    union all select "Vessel" from raw."TrackT"
    union all select upper(substring(name from '^[0-9]{8}-([A-Za-z0-9]+)')) from ci.track_files
) x where v is not null and btrim(v) <> ''
on conflict do nothing;

delete from raw."VesselT" v
where v."VesselID" not in (select "VesselID" from raw."TrackT" where "VesselID" is not null)
  and coalesce(ci.kt(v."VesselCode"), '') not in (select t from ci.vessel_text)
  and coalesce(ci.kt(v."VesselName"), '') not in (select t from ci.vessel_text);

delete from raw."ResearchGroupT" g
where g."ResearchGroupID" not in (select "ResearchGroupID" from raw."TrackT" where "ResearchGroupID" is not null)
  and g."ResearchGroupID" not in (select "ResearchGroupID" from raw."VesselT" where "ResearchGroupID" is not null)
  and coalesce(ci.kt(g."Code"), '') not in (
      select ci.kt(x) from (
          select "Research Group" x from raw."DailyEffortT" union select "Research Group" from raw."SightingT"
          union select "Research Group" from raw."TrackT") u where x is not null);

-- The list of track files DB167 knew of: only the kept tracks' files and the shipped ones.
delete from raw."TrackFileList" f
where lower(btrim(f."FileName")) not in (select lower(btrim("TrackFileName")) from raw."TrackT")
  and lower(btrim(f."FileName")) not in (select lower(btrim(name)) from ci.track_files);

-- Every other raw table: the structure stays, the rows go.
do $$
declare t text;
begin
  for t in select table_name from information_schema.tables
           where table_schema = 'raw' and table_type = 'BASE TABLE'
             and table_name not in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'EffortCrewT', 'EventCodeT', 'IdentificationT',
                                    'IndividualT', 'OtherSpeciesT', 'ResearchGroupT', 'SampleT', 'SightingEventT',
                                    'SightingT', 'SourceT', 'SpeciesT', 'TagSummaryT', 'TrackCompleteCodeT',
                                    'TrackFileList', 'TrackT', 'VesselT')
  loop
    execute format('truncate raw.%I', t);
  end loop;
end $$;

-- ---------------------------------------------------- The three persistent tables
-- Geometry only for the files that are shipped; the rest of the tracks have no
-- line, which is a state the pipeline has to handle (a matched track with no
-- points is "blank").
delete from app.track_geometry g
where lower(btrim(g.object_key)) not in (select lower(btrim(name)) from ci.track_files);
-- The audit log entries about records the cut removed (none expected: every
-- entry's records were kept above; seed_checks.sql proves it).
delete from app.vessel_number n
where n.vessel_key not in (select 'code:' || ci.kt("VesselCode") from raw."VesselT" where ci.kt("VesselCode") is not null)
  and n.vessel_key not in (select 'text:' || t from ci.vessel_text);
