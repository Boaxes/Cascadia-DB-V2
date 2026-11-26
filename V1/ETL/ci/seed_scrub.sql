-- Step 3 of ops/build-ci-seed.sh: remove every personal detail from the cut-down
-- copy, and put in three made-up users. Runs in the scratch database, after
-- seed_subset.sql. Takes the psql variable admin_hash (the made-up superuser's
-- password hash, made by the script).
--
-- No name appears in this file. Every name to remove is read from the data
-- itself, from the columns that hold people, so the script never has to be
-- told who anyone is. (A name that appears only in a comment, never in one of
-- the columns that hold people, cannot be found that way: seed_checks.sql
-- looks for those and stops the script if it finds any.)
--
-- What it does:
--   1. columns that hold a person (photographers, who sampled, who recorded,
--      the crew list, who entered the photo data, the crew names): replaced by a stable
--      generic token, "Observer 12" for a person, "Crew 7" for a crew list.
--      The same text always becomes the same token.
--   2. every word taken from those columns (a first name, a last name, a set
--      of initials) is then replaced wherever else it appears in the text and
--      identifier columns (comments, photo file names such as 20190703-XYZ-0019.jpg,
--      folder paths, permit holders): "Obs12". The vessel codes and a few
--      plain words are never replaced.
--   3. email addresses, web addresses and phone numbers in any text column
--   3b. a name that appears only in a comment cannot be found from the columns
--      that hold people, so the free-text columns are cleaned the other way
--      round: a word is kept only if it is an ordinary English word (the
--      builder's dictionary, with first names taken out of it) or it is used in
--      one of the data's own vocabularies (species, vessels, places, behaviours,
--      the columns that choose from a list). Any other word, which includes the
--      names, is replaced by a stable token ("w17"). Misspellings go too.
--   4. the website's audit log: who made each entry, and the same words
--   5. users, their groups, sessions and the admin's log: all removed, then
--      three made-up users put in
set client_min_messages = warning;
set session_replication_role = replica;

-- ------------------------------- 0. the data's own vocabularies (words that are never taken out)
-- ci.dict is loaded by the script: the dictionary's words, in lower case, less
-- the first names in its list of proper names.
-- src says where a word came from: 'lookup' (the lookup tables and the place
-- columns: never a person) or 'choice' (the columns that choose from a list,
-- where a photographer's initials can sit in a photo file name).
create table ci.allowed (w text primary key, src text);
insert into ci.allowed values ('obs', 'lookup'), ('crew', 'lookup'), ('observer', 'lookup');
do $$
declare c record;
begin
  -- the lookup tables
  for c in select table_name t, column_name col from information_schema.columns
           where table_schema = 'raw' and data_type in ('text', 'character varying')
             and table_name in ('SpeciesT', 'VesselT', 'EventCodeT', 'SourceT', 'TrackCompleteCodeT', 'ResearchGroupT')
  loop
    execute format('insert into ci.allowed select distinct lower(m[1]), ''lookup'' from raw.%I, regexp_matches(%I, ''[A-Za-z]{2,}'', ''g'') m on conflict do nothing', c.t, c.col);
  end loop;
  -- the place columns, then the columns that choose from a list
  for c in select i.table_name t, i.column_name col, (i.column_name in ('Locality', 'Launch', 'Return', 'Region', 'Sub-area', 'Survey Type')) as place
           from information_schema.columns i
           where i.table_schema = 'raw' and i.data_type in ('text', 'character varying')
             and i.table_name in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'IdentificationT', 'OtherSpeciesT',
                                  'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT')
             and (i.column_name in ('Locality', 'Launch', 'Return', 'Region', 'Sub-area', 'Survey Type')
                  or exists (select 1 from ci.column_kinds k where k.table_name = i.table_name and k.column_name = i.column_name and k.kind = 'choice'))
             and i.column_name not in ('Personnel', 'Photographer 1', 'Photographer 2', 'Photographer 3', 'Obs1', 'Sampled by',
                                       'PhotoDataBy', 'ObsL', 'ObsR', 'Rec', 'CrewName', 'Initials', 'Permit', 'Project/Objective')
  loop
    execute format('insert into ci.allowed select distinct lower(m[1]), %L from raw.%I, regexp_matches(%I, ''[A-Za-z]{2,}'', ''g'') m
                    on conflict (w) do update set src = ''lookup'' where excluded.src = ''lookup''',
                   case when c.place then 'lookup' else 'choice' end, c.t, c.col);
  end loop;
end $$;

-- --------------------------------------------------------------- 1. people
create table ci.person_value (v text primary key, token text);
insert into ci.person_value (v)
select distinct lower(btrim(x)) from (
    select "Photographer 1" x from raw."SightingT"
    union all select "Photographer 2" from raw."SightingT"
    union all select "Photographer 3" from raw."SightingT"
    union all select "Obs1" from raw."SightingT"
    union all select "Sampled by" from raw."SampleT"
    union all select "PhotoDataBy" from raw."DailyEffortT"
    union all select "ObsL" from raw."DailyEventT"
    union all select "ObsR" from raw."DailyEventT"
    union all select "Rec" from raw."DailyEventT"
    union all select "CrewName" from raw."EffortCrewT"
    union all select "Initials" from raw."EffortCrewT"
) t
where x is not null and lower(btrim(x)) not in ('', 'na', 'n/a', 'not entered', 'crc');

update ci.person_value p set token = 'Observer ' || r.n
from (select v, row_number() over (order by v) n from ci.person_value) r where r.v = p.v;

-- The free-text columns: every text column of the record tables that
-- column_kinds.csv calls free (or does not list, which the pipeline treats as free).
create table ci.free_col as
select t.table_name, t.column_name from information_schema.columns t
where t.table_schema = 'raw' and t.data_type in ('text', 'character varying')
  and t.table_name in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'IdentificationT', 'OtherSpeciesT',
                       'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT')
  and t.column_name not in ('Research Group', 'Vessel', 'AltVessel', 'Sighting', 'Species', 'Code', 'SourceDB',
                            'TrackFileName', 'TrackFileType', 'Personnel', 'Photographer 1', 'Photographer 2',
                            'Photographer 3', 'Obs1', 'Sampled by', 'PhotoDataBy', 'ObsL', 'ObsR', 'Rec', 'CrewName', 'Initials')
  -- (Project/Objective and Permit are choice columns, but projects are named after
  -- people, as in a first name followed by "Tagging", and a permit holder's
  -- initials end a permit.)
  and (coalesce((select k.kind from ci.column_kinds k where k.table_name = t.table_name and k.column_name = t.column_name), 'free') = 'free'
       or t.column_name in ('Project/Objective', 'Permit'));

-- How often each word is used in the free text (as it stands, before any word
-- is taken out): an ordinary word that is used a lot there is a word, not a name.
create table ci.free_use (w text primary key, n integer);
do $$
declare c record;
begin
  for c in select table_name t, column_name col from ci.free_col loop
    execute format('insert into ci.free_use select lower(m[1]), count(*) from raw.%I, regexp_matches(%I, ''[A-Za-z]{2,}'', ''g'') m
                    group by 1 on conflict (w) do update set n = ci.free_use.n + excluded.n', c.t, c.col);
  end loop;
end $$;

-- The words to find elsewhere: every word of every name in the source
-- (ci.name_text), of any length, in any case, whether or not it is also an
-- ordinary word (a first name that is a dictionary word, two-letter initials).
-- An ordinary word is taken if it ever stands in a column that holds only
-- people, or is ever written with a capital in the free crew list (Personnel),
-- unless the free text uses it more than 20 times: then it is a word that
-- people write (camera, whale, pacific), not a name, and replacing it would
-- ruin every comment. (seed_checks.sql lists those words.)
-- Taken out of the list, and so left alone, are only:
--   - the codes the data uses as keys: vessel codes and names (VesselT and the
--     vessels typed in the data), species codes (SpeciesT.Abbreviation and the
--     species typed in the data), Research Group codes (ResearchGroupT and the
--     groups typed in the data), and event codes (EventCodeT)
--   - a few words that glue a sentence together, without which a comment
--     would stop being readable (and, the, with ...) and the words this script
--     itself writes (Crew, Observer)
-- The words that were taken out for being codes are listed by seed_checks.sql.
create table ci.word (word text primary key, case_free boolean, lkey text, token text);
create table ci.kept_code (word text primary key, why text);
insert into ci.kept_code
select distinct w, 'vessel' from (
    select regexp_split_to_table(t, '[^a-z]+') w from ci.vessel_text
    union select regexp_split_to_table(ci.kt("VesselCode"), '[^a-z]+') from raw."VesselT"
    union select regexp_split_to_table(ci.kt("VesselName"), '[^a-z]+') from raw."VesselT") v where length(w) >= 2
on conflict do nothing;
insert into ci.kept_code
select distinct w, 'species' from (
    -- (a code such as ALC-TP is one code: the TP in it is not set aside)
    select ci.kt("Abbreviation") w from raw."SpeciesT"
    union select ci.kt(sp) from (
        select "Species" sp from raw."SightingT" union select "Species" from raw."OtherSpeciesT"
        union select "Species" from raw."IdentificationT" union select "Species" from raw."SampleT") z where sp is not null) v
where length(w) >= 2 on conflict do nothing;
insert into ci.kept_code
select distinct w, 'research group' from (
    select ci.kt("Code") w from raw."ResearchGroupT"
    union select ci.kt(g) from (
        select "Research Group" g from raw."DailyEffortT" union select "Research Group" from raw."SightingT") z where g is not null) v
where length(w) >= 2 on conflict do nothing;
insert into ci.kept_code
select distinct w, 'event code' from (
    select ci.kt("EventCode") w from raw."EventCodeT") v where length(w) >= 2 on conflict do nothing;

insert into ci.word (word, case_free, lkey)
select w, true, w from (
    select lower(nt.wd) as w,
           bool_or(nt.clean) as in_people_column,
           bool_or(nt.wd ~ '^[A-Z]') as ever_capitalised
    from (select regexp_split_to_table(x, '[^A-Za-z]+') as wd, clean from ci.name_text) nt
    where length(nt.wd) >= 2
    group by lower(nt.wd)
) b
where (not exists (select 1 from ci.dict d where d.w = b.w)
       or ((in_people_column or ever_capitalised) and coalesce((select u.n from ci.free_use u where u.w = b.w), 0) <= 20))
  and w not in ('na', 'not', 'entered', 'and', 'the', 'with', 'for', 'of', 'to', 'by', 'on', 'at', 'in', 'an', 'as', 'is',
                'it', 'or', 'if', 'we', 'so', 'no', 'up', 'me', 'my', 'be', 'do', 'he', 'are', 'was', 'from', 'that',
                'this', 'but', 'all', 'out', 'off', 'film', 'grp', 'crew', 'observer', 'obs', 'team', 'staff', 'trip',
                'drone', 'tag', 'tagging', 'student', 'students')
  and w not in (select kc.word from ci.kept_code kc);
create index on ci.word (lkey);
update ci.word w set token = 'Obs' || r.n || 'x'
from (select word, row_number() over (order by word) n from ci.word) r where r.word = w.word;

create table ci.pat as
select
  '(^|[^A-Za-z])(' || coalesce((select string_agg(word, '|' order by word) from ci.word where case_free), 'zzzzzz') || ')(?![A-Za-z])' as free_pat,
  '(^|[^A-Za-z])(' || coalesce((select string_agg(word, '|' order by word) from ci.word where not case_free), 'zzzzzz') || ')(?![A-Za-z])' as exact_pat;

-- The plain rule: a whole word of letters that is a taken word. Used on the
-- audit log's JSON (whose keys must not change), and inside ci.scrub_text.
create function ci.scrub_text_plain(v text) returns text language plpgsql stable as $$
declare r record;
begin
  if v is null then return null; end if;
  for r in select distinct m[1] as t, w.token from regexp_matches(v, '([A-Za-z]{2,})', 'g') m
           join ci.word w on w.lkey = lower(m[1]) loop
    v := regexp_replace(v, '(?<![A-Za-z])' || r.t || '(?![A-Za-z])', r.token, 'g');
  end loop;
  return v;
end $$;

-- The full rule, for text. A run of letters is replaced as a whole when
--   - it is a taken word (as a whole, even if it has capitals inside, as in MnS), or
--   - a piece of it is: a name glued to another (AllisonLui, JACSmith) is split
--     where the case changes, and each piece tested; the pieces of a path or a
--     file name (split at hyphens, underscores, backslashes, dots) are already
--     separate runs of letters and are tested the same way, or
--   - it is a taken word of three letters or more with an s on the end (a
--     possessive: jenns, jenn's; the apostrophe makes jenn a run of its own),
--     unless that is itself an ordinary or vocabulary word.
-- The codes set aside in ci.kept_code are not in ci.word, so they never match.
create function ci.taken_tokens(v text) returns table (t text, token text) language sql stable as $$
    with pieces as (
        select tk.t, lower(piece) as p
        from (select distinct m[1] as t from regexp_matches(v, '([A-Za-z]{2,})', 'g') m) tk
        cross join lateral regexp_split_to_table(
            regexp_replace(regexp_replace(tk.t, '([a-z])([A-Z])', '\1 \2', 'g'), '([A-Z]+)([A-Z][a-z])', '\1 \2', 'g'), ' ') as piece
        union
        select t, lower(t) from (select distinct m[1] as t from regexp_matches(v, '([A-Za-z]{2,})', 'g') m) whole   -- the run as a whole too
    )
    select x.t, min(x.token) from (
        select pc.t, w.token from pieces pc join ci.word w on w.lkey = pc.p
        union all
        select pc.t, w.token from pieces pc join ci.word w on w.lkey = left(pc.p, -1)
        where length(pc.p) >= 4 and pc.p like '%s'
          and not exists (select 1 from ci.dict d where d.w = pc.p)
          and not exists (select 1 from ci.allowed a where a.w = pc.p)
          and not exists (select 1 from ci.kept_code k where k.word = pc.p)
    ) x group by x.t
$$;

create function ci.scrub_text(v text) returns text language plpgsql stable as $$
declare r record;
begin
  if v is null then return null; end if;
  for r in select t, token from ci.taken_tokens(v) loop
    v := regexp_replace(v, '(?<![A-Za-z])' || r.t || '(?![A-Za-z])', r.token, 'g');
  end loop;
  return v;
end $$;

-- True while a taken word, a piece of a glued name or a possessive is left in v.
-- seed_checks.sql uses it, so a rebuild cannot let one through.
create function ci.has_taken_piece(v text) returns boolean language sql stable as $$
    select exists (select 1 from ci.taken_tokens(v))
$$;

-- 3. also here: contact details.
create function ci.scrub_contact(v text) returns text language sql immutable as $$
    select regexp_replace(
           regexp_replace(
           regexp_replace(v, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', 'email removed', 'g'),
                             '(https?://|www\.)[^\s<>"'']+', 'web address removed', 'gi'),
                             '(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}', 'phone number removed', 'g')
$$;

-- The columns that hold a person: wholesale.
update raw."SightingT" set
    "Photographer 1" = coalesce((select token from ci.person_value where v = lower(btrim("Photographer 1"))), "Photographer 1"),
    "Photographer 2" = coalesce((select token from ci.person_value where v = lower(btrim("Photographer 2"))), "Photographer 2"),
    "Photographer 3" = coalesce((select token from ci.person_value where v = lower(btrim("Photographer 3"))), "Photographer 3"),
    "Obs1"           = coalesce((select token from ci.person_value where v = lower(btrim("Obs1"))), "Obs1");
update raw."SampleT" set "Sampled by" =
    coalesce((select token from ci.person_value where v = lower(btrim("Sampled by"))), "Sampled by");
update raw."DailyEffortT" set "PhotoDataBy" =
    coalesce((select token from ci.person_value where v = lower(btrim("PhotoDataBy"))), "PhotoDataBy");
update raw."EffortCrewT" set
    "CrewName" = coalesce((select token from ci.person_value where v = lower(btrim("CrewName"))), "CrewName"),
    "Initials" = coalesce((select token from ci.person_value where v = lower(btrim("Initials"))), "Initials");
update raw."DailyEventT" set
    "ObsL" = coalesce((select token from ci.person_value where v = lower(btrim("ObsL"))), "ObsL"),
    "ObsR" = coalesce((select token from ci.person_value where v = lower(btrim("ObsR"))), "ObsR"),
    "Rec"  = coalesce((select token from ci.person_value where v = lower(btrim("Rec"))), "Rec");
-- The crew list: one token per distinct list.
update raw."DailyEffortT" e set "Personnel" = 'Crew ' || r.n
from (select p, dense_rank() over (order by p) n
      from (select distinct "Personnel" p from raw."DailyEffortT" where "Personnel" is not null) d) r
where e."Personnel" = r.p;

-- ---------------------------------------- 2. and 3. words and contact details
-- Every text column of the record tables, except the ones the pipeline reads
-- as keys or links (changing those would change the hashes the website's edits
-- are found by) and except the lookup tables (a species abbreviation such as
-- GULL-RB is not a person). Columns that choose from a list are included: a
-- permit holder's initials sit in one.
do $$
declare c record; n integer := 0;
begin
  for c in
    select t.table_name, t.column_name
    from information_schema.columns t
    where t.table_schema = 'raw' and t.data_type in ('text', 'character varying')
      and t.table_name in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'IdentificationT', 'OtherSpeciesT',
                           'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT')
      and t.column_name not in ('Research Group', 'Vessel', 'AltVessel', 'Sighting', 'Species', 'Code', 'SourceDB',
                                'TrackFileName', 'TrackFileType',
                                -- place names, a list the data chooses from
                                'Locality', 'Launch', 'Return', 'Region', 'Sub-area', 'Survey Type',
                                -- already tokens
                                'Personnel', 'Photographer 1', 'Photographer 2', 'Photographer 3', 'Obs1', 'Sampled by',
                                'PhotoDataBy', 'ObsL', 'ObsR', 'Rec', 'CrewName', 'Initials')
  loop
    execute format('update raw.%I set %I = ci.scrub_contact(ci.scrub_text(%I)) where %I is not null and %I is distinct from ci.scrub_contact(ci.scrub_text(%I))',
                   c.table_name, c.column_name, c.column_name, c.column_name, c.column_name, c.column_name);
    n := n + 1;
  end loop;
  raise notice 'words and contact details removed from % columns', n;
end $$;

-- Contact details again, in every text column of every table the seed keeps.
do $$
declare c record;
begin
  for c in
    select t.table_name, t.column_name from information_schema.columns t
    where t.table_schema = 'raw' and t.data_type in ('text', 'character varying')
      and t.table_name in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'EffortCrewT', 'IdentificationT', 'OtherSpeciesT',
                           'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT', 'VesselT')
  loop
    execute format('update raw.%I set %I = ci.scrub_contact(%I) where %I is distinct from ci.scrub_contact(%I)',
                   c.table_name, c.column_name, c.column_name, c.column_name, c.column_name);
  end loop;
end $$;


-- A word is known if it, or the word with a common ending taken off (boats, moved,
-- feeding, slowly), is in the dictionary or the vocabularies.
create function ci.known(word_ text) returns boolean language sql stable as $$
    select exists (select 1 from ci.dict d where d.w = any (array[word_, regexp_replace(word_, 's$', ''), regexp_replace(word_, 'es$', ''),
               regexp_replace(word_, 'ed$', ''), regexp_replace(word_, 'd$', ''), regexp_replace(word_, 'ing$', ''), regexp_replace(word_, 'ing$', 'e'),
               regexp_replace(word_, 'ly$', ''), regexp_replace(word_, 'er$', ''), regexp_replace(word_, 'ies$', 'y'), regexp_replace(word_, 'ied$', 'y'),
               regexp_replace(word_, '(.)\1ed$', '\1'), regexp_replace(word_, '(.)\1ing$', '\1')]))
        or exists (select 1 from ci.allowed a where a.w = any (array[word_, regexp_replace(word_, 's$', ''), regexp_replace(word_, 'es$', '')]))
$$;

-- A capitalised word has to be a dictionary or vocabulary word as it stands (so
-- Holmes and Viers, which a plural-stripping rule would let through, do not
-- pass), apart from an -ed or -ing form of a longer word (Approached).
create function ci.is_known(word_ text) returns boolean language sql stable as $$
    select case
        when word_ ~ '^[A-Z][a-z]+$' then
            exists (select 1 from ci.dict d where d.w = lower(word_)) or exists (select 1 from ci.allowed a where a.w = lower(word_))
            or (word_ ~ '(ed|ing)$' and length(regexp_replace(lower(word_), '(ed|ing)$', '')) >= 4 and ci.known(lower(word_)))
        else ci.known(lower(word_))
    end
$$;

create table ci.unknown (w text primary key, token text);
do $$
declare c record;
begin
  for c in select table_name t, column_name col from ci.free_col loop
    execute format('insert into ci.unknown (w) select distinct m[1] from raw.%I, regexp_matches(%I, ''[A-Za-z]{2,}'', ''g'') m
                    where not ci.is_known(m[1]) on conflict do nothing', c.t, c.col);
  end loop;
end $$;
update ci.unknown u set token = 'w' || r.n || 'x' from (select w, row_number() over (order by w) n from ci.unknown) r where r.w = u.w;

create function ci.scrub_unknown(v text) returns text language plpgsql stable as $$
declare r record;
begin
  if v is null then return null; end if;
  for r in select distinct m[1] as word, u.token from regexp_matches(v, '([A-Za-z]{2,})', 'g') m join ci.unknown u on u.w = m[1] loop
    v := regexp_replace(v, '(?<![A-Za-z])' || r.word || '(?![A-Za-z])', r.token, 'g');
  end loop;
  return v;
end $$;

do $$
declare c record;
begin
  for c in select table_name t, column_name col from ci.free_col loop
    execute format('update raw.%I set %I = ci.scrub_unknown(%I) where %I is not null and %I ~ ''[A-Za-z]{2}''', c.t, c.col, c.col, c.col, c.col);
  end loop;
end $$;

-- ---------------------------------------------------------- 4. the audit log
-- The two people who made entries become two made-up ones, with the ids the
-- made-up users get below.
update app.audit_log set
    actor_name = case when actor_id = 1 then 'CI Admin' else 'CI Editor' end;
update app.audit_log set
    comment  = ci.scrub_contact(ci.scrub_text(comment)),
    changes  = ci.scrub_contact(ci.scrub_text_plain(changes::text))::jsonb,
    snapshot = ci.scrub_contact(ci.scrub_text_plain(snapshot::text))::jsonb;

-- -------------------------------------------------------------- 5. the users
delete from django_admin_log;
delete from django_session;
delete from auth_user_groups;
delete from auth_user_user_permissions;
delete from auth_user;
insert into auth_user (id, password, last_login, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined) values
    (1, :'admin_hash', null, true,  'ci_admin',  'CI', 'Admin',  'ci_admin@example.invalid',  true,  true, '2026-01-01 00:00:00+00'),
    (2, '!ci-seed-no-password-1', null, false, 'ci_editor', 'CI', 'Editor', 'ci_editor@example.invalid', true,  true, '2026-01-01 00:00:00+00'),
    (3, '!ci-seed-no-password-2', null, false, 'ci_viewer', 'CI', 'Viewer', 'ci_viewer@example.invalid', false, true, '2026-01-01 00:00:00+00');
insert into auth_user_groups (user_id, group_id)
select 1, id from auth_group where name = 'Admin'
union all select 2, id from auth_group where name = 'Editor'
union all select 3, id from auth_group where name = 'Viewer';
select setval(pg_get_serial_sequence('auth_user', 'id'), 3);
