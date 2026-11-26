-- Step 4 of ops/build-ci-seed.sh: prove the cut and the scrub. Any failed check
-- stops the script before anything is written. Each line printed is a check
-- that passed.
set client_min_messages = notice;

create function ci.must(ok boolean, what text) returns void language plpgsql as $$
begin
  if ok then raise notice 'ok    %', what; else raise exception 'FAILED %', what; end if;
end $$;

-- ------------------------------------------------ nothing is left pointing at a cut record
do $$
declare n bigint;
begin
  select count(*) into n from raw."SightingT" x where x."DailyEffortID" is null or not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = x."DailyEffortID");
  perform ci.must(n = 0, format('every Sighting has its Effort (%s without)', n));

  select count(*) into n from (
      select "DailyEffortID" from raw."DailyConditionT" union all select "DailyEffortID" from raw."DailyEventT"
      union all select "DailyEffortID" from raw."OtherSpeciesT" union all select "DailyEffortID" from raw."TagSummaryT"
      union all select "DailyEffortID" from raw."SightingEventT" union all select "DailyEffortID" from raw."SampleT"
      union all select "DailyEffortID" from raw."IdentificationT") c
  where not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = c."DailyEffortID");
  perform ci.must(n = 0, format('every child row has its Effort (%s without)', n));

  select count(*) into n from raw."EffortCrewT" x where not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = x."DailyEffortID");
  perform ci.must(n = 0, format('every crew row has its Effort (%s without)', n));

  select count(*) into n from raw."IdentificationT" x where x."SightingID" is not null
     and not exists (select 1 from raw."SightingT" s where s."SightingID" = x."SightingID");
  perform ci.must(n = 0, format('every Identification that names a Sighting has it (%s without)', n));

  select count(*) into n from raw."SampleT" x where x."SightingID" is not null
     and not exists (select 1 from raw."SightingT" s where s."SightingID" = x."SightingID");
  perform ci.must(n = 0, format('every Sample that names a Sighting has it (%s without)', n));

  select count(*) into n from raw."SampleT" x where x."SightingEventID" is not null
     and not exists (select 1 from raw."SightingEventT" s where s."SightingEventID" = x."SightingEventID");
  perform ci.must(n = 0, format('every Sample that names a Sighting Event has it (%s without)', n));

  select count(*) into n from (select "IndividualID" from raw."IdentificationT" union all select "IndividualID" from raw."SampleT") x
     where x."IndividualID" is not null and not exists (select 1 from raw."IndividualT" i where i."IndividualID" = x."IndividualID");
  perform ci.must(n = 0, format('every Individual named is there (%s without)', n));

  -- A track names an Effort that is there, or one DB167 itself removed (the
  -- merged Effort in seeds/removed_efforts.csv), or none.
  select count(*) into n from raw."TrackT" t where t."EffortID" is not null
     and not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = t."EffortID")
     and t."EffortID" not in (select removed_effort from ci.removed);
  perform ci.must(n = 0, format('every Track names an Effort that is there, or a merged one (%s without)', n));

  select count(*) into n from raw."TrackT" t where t."ResearchGroupID" is not null
     and not exists (select 1 from raw."ResearchGroupT" g where g."ResearchGroupID" = t."ResearchGroupID");
  perform ci.must(n = 0, format('every Track Research Group is there (%s without)', n));

  select count(*) into n from raw."TrackT" t where t."VesselID" is not null
     and not exists (select 1 from raw."VesselT" v where v."VesselID" = t."VesselID");
  perform ci.must(n = 0, format('every Track Vessel is there (%s without)', n));

  select count(*) into n from raw."VesselT" v where v."ResearchGroupID" is not null
     and not exists (select 1 from raw."ResearchGroupT" g where g."ResearchGroupID" = v."ResearchGroupID");
  perform ci.must(n = 0, format('every Vessel Research Group is there (%s without)', n));

  -- Typed Research Group and Vessel text resolve to a row in the lookups.
  select count(*) into n from (select distinct "Research Group" g from raw."DailyEffortT" union select "Research Group" from raw."SightingT") x
     where x.g is not null and ci.kt(x.g) not in (select ci.kt("Code") from raw."ResearchGroupT")
       and ci.kt(x.g) not in (select code from ci.group_not_in_source_lookup);
  perform ci.must(n = 0, format('every typed Research Group is in ResearchGroupT, unless the source lacked it too (%s without)', n));

  -- The website's edits all have their records.
  select count(*) into n from app.audit_log a where a.target_table = 'SightingT' and a.legacy_pk is not null
     and not exists (select 1 from raw."SightingT" s where s."SightingID"::text = a.legacy_pk);
  perform ci.must(n = 0, format('every audit log entry about a Sighting has the Sighting (%s without)', n));

  select count(*) into n from app.audit_log a where a.target_table = 'TrackT' and a.action = 'associate'
     and not exists (select 1 from raw."TrackT" t where t."TrackID"::text = a.target_pk);
  perform ci.must(n = 0, format('every track a website edit matched is there (%s without)', n));

  select count(*) into n from app.audit_log a where a.changes ? 'EffortID' and a.changes -> 'EffortID' ->> 'new' is not null
     and not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = (a.changes -> 'EffortID' ->> 'new')::integer)
     and (a.changes -> 'EffortID' ->> 'new')::integer not in (select effort from ci.audit_effort_not_in_source);
  perform ci.must(n = 0, format('every Effort a website edit matched is there, unless the source lacked it too (%s without)', n));

  -- The pipeline's corrections still find their records (ETL/dbt/tests/record_fixes_are_applied.sql).
  select count(*) into n from ci.fixes f where (
      select count(*) from (
          select "DailyEffortID"::text id, "Date"::date d, 'DailyEffortT' t from raw."DailyEffortT"
          union all select "SightingID"::text, "Date"::date, 'SightingT' from raw."SightingT") r
      where r.t = f.table_name and r.id = f.legacy_id and r.d = f.record_date::date) <> 1;
  perform ci.must(n = 0, format('every record fix finds its record exactly once (%s do not)', n));

  select count(*) into n from ci.removed r where not exists (select 1 from raw."DailyEffortT" e where e."DailyEffortID" = r.kept_effort)
     or not exists (select 1 from raw."TrackT" t where t."EffortID" = r.removed_effort);
  perform ci.must(n = 0, format('every merged Effort has its kept Effort and a track (%s do not)', n));

  -- Track files and lines.
  select count(*) into n from app.track_geometry g where g.object_key not in (select name from ci.file_size);
  perform ci.must(n = 0, format('every line in app.track_geometry has its file (%s without)', n));
  select count(*) into n from app.track_geometry where geom is null or point_count is null;
  perform ci.must(n = 0, format('every line has a geometry (%s without)', n));
end $$;

-- What is in it.
select 'efforts' as what, count(*) as n from raw."DailyEffortT"
union all select 'sightings', count(*) from raw."SightingT"
union all select 'identifications', count(*) from raw."IdentificationT"
union all select 'tracks', count(*) from raw."TrackT"
union all select 'track lines', count(*) from app.track_geometry
union all select 'audit log entries', count(*) from app.audit_log
union all select 'efforts with more than one track', count(*) from (
    select "EffortID" from raw."TrackT" where "EffortID" is not null group by 1 having count(*) > 1) m
union all select 'tracks matched', count(*) from raw."TrackT" where "EffortID" is not null
union all select 'tracks not matched', count(*) from raw."TrackT" where "EffortID" is null;

-- ------------------------------------------- words deliberately left alone (printed for the record)
do $$
declare r record;
begin
  for r in select why, string_agg(word, ' ' order by word) as words
           from ci.kept_code where word in (select lower(wd) from (select regexp_split_to_table(x, '[^A-Za-z]+') wd from ci.name_text) t)
           group by why order by why loop
    raise notice 'left alone, a % code that is also a word in a name column: %', r.why, r.words;
  end loop;
  for r in select string_agg(b.w, ' ' order by b.w) as words from (
              select lower(wd) w from (select regexp_split_to_table(x, '[^A-Za-z]+') wd from ci.name_text) t
              where length(wd) >= 2 group by lower(wd)) b
           where exists (select 1 from ci.dict d where d.w = b.w) and coalesce((select u.n from ci.free_use u where u.w = b.w), 0) > 20
             and not exists (select 1 from ci.word x where x.word = b.w) and not exists (select 1 from ci.kept_code k where k.word = b.w) loop
    raise notice 'left alone, ordinary words the free text uses more than 20 times: %', r.words;
  end loop;
end $$;

-- ------------------------------------------------------------ nothing personal is left
do $$
declare n bigint; c record; leaked text := ''; q text; pat_free text; pat_exact text;
begin
  select free_pat, exact_pat into pat_free, pat_exact from ci.pat;

  -- Every column that held a person now holds only a token (or a placeholder).
  select count(*) into n from (
      select "Photographer 1" x from raw."SightingT" union all select "Photographer 2" from raw."SightingT"
      union all select "Photographer 3" from raw."SightingT" union all select "Obs1" from raw."SightingT"
      union all select "Sampled by" from raw."SampleT" union all select "PhotoDataBy" from raw."DailyEffortT"
      union all select "ObsL" from raw."DailyEventT" union all select "ObsR" from raw."DailyEventT"
      union all select "Rec" from raw."DailyEventT" union all select "CrewName" from raw."EffortCrewT"
      union all select "Initials" from raw."EffortCrewT") p
  where x is not null and btrim(x) <> '' and x !~ '^Observer [0-9]+$' and lower(btrim(x)) not in ('na', 'n/a', 'not entered', 'crc');
  perform ci.must(n = 0, format('every person column holds only a token or a placeholder (%s do not)', n));
  select count(*) into n from raw."DailyEffortT" where "Personnel" is not null and "Personnel" !~ '^Crew [0-9]+$';
  perform ci.must(n = 0, format('every crew list is a token (%s are not)', n));

  -- No word taken from those columns, no email, no web address, no phone number,
  -- in any text column of raw, in the audit log, or in Django's tables.
  for c in
    select table_schema s, table_name t, column_name col, data_type dt from information_schema.columns
    where ((table_schema = 'raw' and table_name <> 'TrackFileList') or (table_schema = 'app' and table_name = 'audit_log')
           or (table_schema = 'public' and table_name like 'auth\_%')
           or (table_schema = 'public' and table_name like 'django\_%'))
      and data_type in ('text', 'character varying', 'jsonb')
      and column_name not in ('TrackFileName')
  loop
    -- Taken words are looked for in the record tables (the lookups are left as
    -- they are: GULL-RB is a bird, not a person).
    -- (Sighting is a key, such as COT9, and is left as it is.)
    -- (Species and event codes, such as ALC-TP, are keys; place names are a list the
    -- data chooses from; a password is a hash.)
    if (c.s = 'public' and c.t <> 'auth_user') or c.col in ('Sighting', 'Species', 'Code', 'Locality', 'Launch', 'Return', 'Region', 'Sub-area', 'Survey Type', 'password') then
      q := format('select count(*) from %I.%I where %I::text ~ %L or %I::text ~* %L or %I::text ~ %L',
                  c.s, c.t, c.col, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', c.col, '(https?://|www\.)',
                  c.col, '(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}');
    elsif c.s = 'raw' and c.t not in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'EffortCrewT', 'IdentificationT', 'OtherSpeciesT',
                                    'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT') then
      q := format('select count(*) from %I.%I where %I::text ~ %L or %I::text ~* %L or %I::text ~ %L',
                  c.s, c.t, c.col, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', c.col, '(https?://|www\.)',
                  c.col, '(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}');
    else
      q := format('select count(*) from %I.%I where %I::text ~* %L or %I::text ~ %L or %I::text ~ %L or %I::text ~* %L or %I::text ~ %L',
                  c.s, c.t, c.col, pat_free, c.col, pat_exact,
                  c.col, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', c.col, '(https?://|www\.)',
                  c.col, '(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}');
    end if;
    execute q into n;
    -- The made-up users' own addresses are the one allowed email.
    if c.s = 'public' and c.t = 'auth_user' and c.col = 'email' then continue; end if;
    if n > 0 then leaked := leaked || format(' %s.%s.%s(%s)', c.s, c.t, c.col, n); end if;
  end loop;
  -- (ci.word holds every word of every name column, any length, any case, less the codes
  -- above and a few sentence-glue words; the pattern is built from it.)
  perform ci.must((select count(*) from ci.word) > 1000, 'the list of taken words is the whole source list, not a short one');
  perform ci.must(leaked = '', 'no taken word, email, web address or phone number in any text column' || case when leaked <> '' then ':' || leaked else '' end);

  -- Nor does a name glued to another (AllisonLui), a piece of a path, or a taken word with an s
  -- on the end (a possessive), in any text column a word could hide in.
  leaked := '';
  for c in select table_name t, column_name col from information_schema.columns
           where table_schema = 'raw' and data_type in ('text', 'character varying')
             and table_name in ('DailyConditionT', 'DailyEffortT', 'DailyEventT', 'EffortCrewT', 'IdentificationT', 'OtherSpeciesT',
                                'SampleT', 'SightingEventT', 'SightingT', 'TagSummaryT', 'TrackT')
             and column_name not in ('Research Group', 'Vessel', 'AltVessel', 'Sighting', 'Species', 'Code', 'SourceDB',
                                     'TrackFileName', 'TrackFileType', 'Locality', 'Launch', 'Return', 'Region', 'Sub-area', 'Survey Type')
  loop
    execute format('select count(*) from raw.%I where ci.has_taken_piece(%I)', c.t, c.col) into n;
    if n > 0 then leaked := leaked || format(' raw.%s.%s(%s)', c.t, c.col, n); end if;
  end loop;
  select count(*) into n from app.audit_log where ci.has_taken_piece(comment);
  if n > 0 then leaked := leaked || format(' app.audit_log.comment(%s)', n); end if;
  perform ci.must(leaked = '', 'no glued name, path piece or possessive of a taken word in any text column'
                  || case when leaked <> '' then ':' || leaked else '' end);

  -- Track file names carry no taken word either.
  select count(*) into n from (select "TrackFileName" x from raw."TrackT" union all select "FileName" from raw."TrackFileList" union all select object_key from app.track_geometry) f
  where x ~* pat_free or x ~ pat_exact;
  perform ci.must(n = 0, format('no track file name carries a taken word (%s do)', n));

  -- Free text holds only dictionary words, words from the data's own vocabularies, and tokens.
  -- (The audit log's comments are written by the application, and were read
  -- through by hand: none names anyone.)
  leaked := '';
  for c in select table_name t, column_name col from ci.free_col loop
    execute format('select count(*) from (select m[1] w from raw.%I, regexp_matches(%I, ''[A-Za-z]{2,}'', ''g'') m) x
                    where not ci.is_known(x.w)', c.t, c.col) into n;
    if n > 0 then leaked := leaked || format(' %s.%s(%s)', c.t, c.col, n); end if;
  end loop;
  perform ci.must(leaked = '', 'free text holds only known words' || case when leaked <> '' then ':' || leaked else '' end);

  -- Users.
  select count(*) into n from auth_user;
  perform ci.must(n = 3, format('three users (%s)', n));
  perform ci.must((select count(*) from auth_user where username not in ('ci_admin', 'ci_editor', 'ci_viewer')) = 0, 'only the made-up users');
  perform ci.must((select count(*) from auth_user where email not like '%@example.invalid') = 0, 'only made-up email addresses');
  perform ci.must((select count(*) from django_session) = 0 and (select count(*) from django_admin_log) = 0, 'no sessions and no admin log');
  perform ci.must((select count(distinct actor_name) from app.audit_log) <= 2
                  and (select count(*) from app.audit_log where actor_name not in ('CI Admin', 'CI Editor')) = 0, 'audit log entries are by CI Admin or CI Editor');
  perform ci.must((select count(*) from raw."ResearchGroupT" where "Code" not in ('CRC', 'AOP')) = 0,
                  'the Research Group lookup holds only the groups the kept records use (CRC, AOP)');
end $$;
