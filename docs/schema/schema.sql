-- Unified DB gold schema for PostgreSQL 18 with PostGIS 3.6.
-- Design: docs/schema/schema.md. Decisions: docs/schema/decisions/.
--
-- Versioned tables (decision 004). Every data table except the lookups holds one row per version
-- of a record. The same version columns end each of them:
--   version_id       one version (identity)
--   id               the record, shared by all its versions (hashed key, decision 002)
--   valid_from       when this version took effect
--   valid_to         when a later version replaced it; null on the current version
--   deleted          true on a version that removes the record
--   change_type      load (pipeline's first version), edit, delete, restore, or a Track File Manager action
--   change_source    site or pipeline
--   changed_by       the Django user (auth_user.id); null for the pipeline
--   pipeline_run_id  the pipeline run that wrote it; null for the site
--   change_reason    the person's note, if any
--   change_id        shared by every row one action wrote (a delete with its dependents)
-- A record's current version is the row with valid_to null. Pages read the <table>_current views,
-- which also leave out deleted records. Links between tables name the record id, so they are
-- checked by dbt tests and Phase 3 checks, not by foreign keys (Q-067).
-- Index predicate "where valid_to is null and not deleted" matches the _current views, so the
-- planner uses those partial indexes for every page query.

create extension if not exists postgis;
create extension if not exists pg_trgm;

create schema if not exists gold;

-- Lookups: written by the pipeline only, never versioned -------------------------------------

create table gold.pipeline_run (
    run_id       text primary key,
    started_at   timestamptz not null,
    finished_at  timestamptz,
    result       text not null,
    git_commit   text,
    run_url      text
);

create table gold.species (
    id               bigint primary key,
    code             text not null unique,
    common_name      text,
    scientific_name  text,
    category         text not null check (category in ('cetacean', 'pinniped', 'other_marine', 'unidentified', 'non_animal')),
    animal_group     text
);
-- Search by name with typos (SRCH-02).
create index species_common_name_trgm on gold.species using gin (common_name gin_trgm_ops);
create index species_scientific_name_trgm on gold.species using gin (scientific_name gin_trgm_ops);

create table gold.vessel (
    id         bigint primary key,
    legacy_id  integer unique,
    code       text not null unique,
    name       text not null,
    aliases    text[] not null default '{}'
);
-- Search by vessel name (SRCH-01).
create index vessel_name_trgm on gold.vessel using gin (name gin_trgm_ops);

create table gold.research_group (
    id              bigint primary key,
    code            text not null unique,
    name            text,
    sharing_status  text check (sharing_status in ('public', 'private'))
);

create table gold.event_code (
    id           bigint primary key,
    code         text not null unique,
    name         text,
    description  text,
    sort_order   integer
);

-- Land shrunk inward by 1 km and cut into small pieces, for Sightings on Land (FILT-01).
-- A sighting within 1 km of the coast is never on land, as in V1.
create table gold.land_inland (
    id    bigint generated always as identity primary key,
    geom  geometry(Polygon, 4326) not null
);
-- is_on_land(): sighting position against land pieces.
create index land_inland_geom on gold.land_inland using gist (geom);

create function gold.is_on_land(point_geom geometry) returns boolean
language sql stable as $$
    select point_geom is not null
       and exists (select 1 from gold.land_inland l where l.geom && point_geom and ST_Intersects(l.geom, point_geom))
$$;

-- IDs as typed: upper case, letters and digits only. Search strips a leading CRC (SRCH-02).
create function gold.normalize_id(value text) returns text
language sql immutable parallel safe as $$
    select nullif(regexp_replace(upper(value), '[^A-Z0-9]', '', 'g'), '')
$$;

-- Survey records -------------------------------------------------------------------------------

create table gold.daily_effort (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    research_group_id    bigint not null references gold.research_group,
    vessel_id            bigint not null references gold.vessel,
    effort_date          date not null,
    start_time           time,
    end_time             time,
    locality             text,
    launch               text,
    return_location      text,
    region               text,
    sub_area             text,
    survey_type          text,
    project_objective    text,
    personnel            text,
    comments             text,
    time_off_effort      interval,
    time_searching       interval,
    distance_nm          numeric(6, 3),
    start_geom           geometry(Point, 4326),
    start_source         text check (start_source in ('event_B', 'gps_track', 'first_positioned_record')),
    end_geom             geometry(Point, 4326),
    end_source           text check (end_source in ('event_T', 'gps_track')),
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
-- One current version per record and per legacy ID; /efforts/<legacy_id>/ (EDET).
create unique index daily_effort_current_id on gold.daily_effort (id) where valid_to is null;
create unique index daily_effort_current_legacy on gold.daily_effort (legacy_id) where valid_to is null;
-- History of one record in time order (HIST-03).
create index daily_effort_versions on gold.daily_effort (id, valid_from);
-- Efforts list, newest first, and the Years, Months and Exact Dates filters (EFF-02, FILT-01).
create index daily_effort_date on gold.daily_effort (effort_date desc) where valid_to is null and not deleted;
-- Vessel and Research Group filters (FILT-01, FILT-02 default CRC).
create index daily_effort_vessel on gold.daily_effort (vessel_id) where valid_to is null and not deleted;
create index daily_effort_research_group on gold.daily_effort (research_group_id, effort_date desc) where valid_to is null and not deleted;
-- Audit Log grouped by action (AUD-01).
create index daily_effort_change on gold.daily_effort (change_id);

create table gold.sighting (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    research_group_id    bigint not null references gold.research_group,
    vessel_id            bigint not null references gold.vessel,
    species_id           bigint references gold.species,
    species_raw          text,
    species_uncertain    boolean not null default false,
    sighting_number      text,
    sighting_date        date not null,
    sighting_time        time,
    geom                 geometry(Point, 4326),
    end_geom             geometry(Point, 4326),
    on_land              boolean not null default false,
    position_type        text check (position_type in ('Precise', 'Calculated', 'Estimated', 'General')),
    sight_type           text check (sight_type in ('S', 'SBE', 'SE', 'Sb', 'UNK')),
    est_size_best        integer,
    est_size_min         integer,
    est_size_max         integer,
    num_calves           integer,
    group_behavior       text,
    group_type           text,
    depth_m              numeric(7, 2),
    photos_taken         boolean not null default false,
    bearing              integer,
    range_m              integer,
    reticle              double precision,
    range_source         text,
    photo_series         text,
    photo_frames         text,
    photographer         text,
    comments             text,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
-- One current version per record and legacy ID; /sightings/<legacy_id>/ and ID search (SDET, SRCH-01).
create unique index sighting_current_id on gold.sighting (id) where valid_to is null;
create unique index sighting_current_legacy on gold.sighting (legacy_id) where valid_to is null;
create index sighting_versions on gold.sighting (id, valid_from);
-- Sightings of one effort: effort page, timeline, Only Efforts With Matching Sightings (EDET-06, EDET-09, FILT-03).
create index sighting_effort on gold.sighting (daily_effort_id) where valid_to is null and not deleted;
-- Sightings list newest first, and the date filters (SIGHT-02).
create index sighting_date on gold.sighting (sighting_date desc, sighting_time desc) where valid_to is null and not deleted;
-- Species filter and the species legend (FILT-01, EXPL-03).
create index sighting_species on gold.sighting (species_id, sighting_date desc) where valid_to is null and not deleted;
create index sighting_research_group on gold.sighting (research_group_id, sighting_date desc) where valid_to is null and not deleted;
-- Explore: positioned sightings in the map view, and Draw an Area (EXPL-02, EXPL-04).
create index sighting_geom on gold.sighting using gist (geom) where valid_to is null and not deleted;
create index sighting_change on gold.sighting (change_id);

create table gold.daily_condition (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    research_group_id    bigint not null references gold.research_group,
    vessel_id            bigint not null references gold.vessel,
    observed_at          timestamp not null,
    geom                 geometry(Point, 4326),
    beaufort             smallint,
    swell_ft             smallint,
    cloud_cover_pct      smallint,
    precipitation        text,
    quality              text,
    visibility_nm        numeric(5, 2),
    comments             text,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index daily_condition_current_id on gold.daily_condition (id) where valid_to is null;
create index daily_condition_versions on gold.daily_condition (id, valid_from);
-- Effort timeline and the Weather sheet, in time order (EDET-09, EXP-03, TRACK-03 timeline events).
create index daily_condition_effort on gold.daily_condition (daily_effort_id, observed_at) where valid_to is null and not deleted;
create index daily_condition_change on gold.daily_condition (change_id);

create table gold.daily_event (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    research_group_id    bigint not null references gold.research_group,
    vessel_id            bigint not null references gold.vessel,
    event_code_id        bigint references gold.event_code,
    event_at             timestamp not null,
    geom                 geometry(Point, 4326),
    observer_left        text,
    observer_right       text,
    recorder             text,
    comments             text,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index daily_event_current_id on gold.daily_event (id) where valid_to is null;
create index daily_event_versions on gold.daily_event (id, valid_from);
-- Effort timeline, Timeline sheet and no-track path in time order (EDET-05, EDET-09, TRACK-08).
create index daily_event_effort on gold.daily_event (daily_effort_id, event_at) where valid_to is null and not deleted;
create index daily_event_change on gold.daily_event (change_id);

-- Records attached to a sighting ---------------------------------------------------------------

create table gold.sighting_event (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    sighting_id          bigint,
    research_group_id    bigint not null references gold.research_group,
    vessel_id            bigint not null references gold.vessel,
    event_at             timestamp not null,
    event_label          text,
    event_ref            text,
    geom                 geometry(Point, 4326),
    position_type        text,
    bearing              text,
    range_m              integer,
    reaction_count       integer,
    reaction             text,
    field_id             text,
    comments             text,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index sighting_event_current_id on gold.sighting_event (id) where valid_to is null;
create index sighting_event_versions on gold.sighting_event (id, valid_from);
-- Sighting Events on the sighting page and sheet (SDET-07, EXP-03).
create index sighting_event_sighting on gold.sighting_event (sighting_id, event_at) where valid_to is null and not deleted;
create index sighting_event_change on gold.sighting_event (change_id);

create table gold.other_species (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    sighting_id          bigint,
    research_group_id    bigint references gold.research_group,
    vessel_id            bigint references gold.vessel,
    seen_on              date,
    species_id           bigint references gold.species,
    species_raw          text,
    animal_class         text,
    animal_count         integer,
    comments             text,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index other_species_current_id on gold.other_species (id) where valid_to is null;
create index other_species_versions on gold.other_species (id, valid_from);
-- Other Species Present on the sighting page (SDET-07).
create index other_species_sighting on gold.other_species (sighting_id) where valid_to is null and not deleted;
create index other_species_change on gold.other_species (change_id);

create table gold.tag_deployment (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer not null,
    daily_effort_id      bigint,
    sighting_id          bigint,
    research_group_id    bigint references gold.research_group,
    vessel_id            bigint references gold.vessel,
    tag_number           text,
    tag_type             text,
    deploy_type          text,
    deployed_at          timestamp,
    deploy_body_location text,
    deploy_reaction      text,
    tag_off_at           timestamp,
    data_file            text,
    vhf_channel          double precision,
    video                text,
    field_id             text,
    comments             text,
    extra                jsonb not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index tag_deployment_current_id on gold.tag_deployment (id) where valid_to is null;
create index tag_deployment_versions on gold.tag_deployment (id, valid_from);
-- Tag Deployments on the sighting page and the Tags and Samples filter (SDET-07, FILT-01).
create index tag_deployment_sighting on gold.tag_deployment (sighting_id) where valid_to is null and not deleted;
create index tag_deployment_change on gold.tag_deployment (change_id);

-- Photo-ID (decision 001) ----------------------------------------------------------------------

create table gold.individual (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    catalog              text not null,
    catalog_number       integer not null,
    species_id           bigint not null references gold.species,
    sex                  text check (sex in ('F', 'M', 'U')),
    sex_basis            text check (sex_basis in ('genetic', 'behavioural')),
    colour_category      text,
    dead                 boolean not null default false,
    dead_confirmed_on    date,
    other_ids            jsonb not null default '{}',
    search_ids           text[] not null default '{}',
    extra                jsonb not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index individual_current_id on gold.individual (id) where valid_to is null;
-- One current whale per catalog number; the URL /individuals/<catalog>-<number>/ (IDET).
create unique index individual_current_number on gold.individual (catalog, catalog_number) where valid_to is null;
create index individual_versions on gold.individual (id, valid_from);
-- Any ID, alias, retired or cross-catalog ID finds the whale (SRCH-02, IND-02, FILT-04).
create index individual_search_ids on gold.individual using gin (search_ids) where valid_to is null and not deleted;
-- Species filter on the Individuals list (IND-02).
create index individual_species on gold.individual (species_id) where valid_to is null and not deleted;

create table gold.identification (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer,
    source               text not null,
    individual_id        bigint,
    sighting_id          bigint,
    research_group_id    bigint references gold.research_group,
    contributor          text,
    seen_on              date not null,
    seen_time            time,
    geom                 geometry(Point, 4326),
    region               text,
    sub_area             text,
    locality             text,
    sharing_status       text check (sharing_status in ('public', 'private')),
    quality              text,
    happywhale_url       text,
    field_id             text,
    record_type          text,
    extra                jsonb not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index identification_current_id on gold.identification (id) where valid_to is null;
create index identification_versions on gold.identification (id, valid_from);
-- An individual's sightings newest first, its map, First and Last Seen (IDET-04, IDET-05, IND-01).
create index identification_individual on gold.identification (individual_id, seen_on desc) where valid_to is null and not deleted;
-- Individuals Identified on a sighting, Individual filter, Survey Sightings (SDET-07, FILT-04, IDET-07).
create index identification_sighting on gold.identification (sighting_id) where valid_to is null and not deleted;
create index identification_change on gold.identification (change_id);

create table gold.sample (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer,
    source               text not null,
    daily_effort_id      bigint,
    sighting_id          bigint,
    individual_id        bigint,
    research_group_id    bigint references gold.research_group,
    vessel_id            bigint references gold.vessel,
    species_id           bigint references gold.species,
    sample_number        text,
    sample_type          text,
    sampled_at           timestamp,
    certainty_of_id      text,
    preservation         text,
    sampled_by           text,
    field_id             text,
    reaction             text,
    comments             text,
    extra                jsonb not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index sample_current_id on gold.sample (id) where valid_to is null;
create index sample_versions on gold.sample (id, valid_from);
-- Samples on the sighting page, the Tags and Samples filter (SDET-06, FILT-01).
create index sample_sighting on gold.sample (sighting_id) where valid_to is null and not deleted;
-- Samples on the Individual page (IDET-06).
create index sample_individual on gold.sample (individual_id) where valid_to is null and not deleted;
-- Sample number search, ignoring case and punctuation (SRCH-01).
create index sample_number_search on gold.sample (gold.normalize_id(sample_number)) where valid_to is null and not deleted;
create index sample_change on gold.sample (change_id);

-- GPS tracks (decision 003). DuckLake holds the points; these are the metadata and the copy. ----

create table gold.track (
    version_id           bigint generated always as identity primary key,
    id                   bigint not null,
    legacy_id            integer,
    daily_effort_id      bigint,
    file_name            text not null,
    status               text not null check (status in ('matched', 'not_matched', 'blank')),
    track_source         text check (track_source in ('Handheld GPS', 'Tablet', 'Plotter', 'Other')),
    complete_code        text,
    usable               boolean not null default true,
    comments             text,
    ducklake_snapshot_id bigint,
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    deleted          boolean not null default false,
    change_type      text not null check (change_type in ('load', 'edit', 'delete', 'restore', 'import',
                                                          'replace_points', 'match', 'unmatch', 'create_from_positions')),
    change_source    text not null check (change_source in ('site', 'pipeline')),
    changed_by       integer,
    pipeline_run_id  text references gold.pipeline_run,
    change_reason    text,
    change_id        uuid not null,
    check (valid_to is null or valid_to > valid_from),
    check ((change_source = 'site') = (changed_by is not null))
);
create unique index track_current_id on gold.track (id) where valid_to is null;
create index track_versions on gold.track (id, valid_from);
-- One track per effort (TFM-06, Q-008).
create unique index track_one_per_effort on gold.track (daily_effort_id)
    where valid_to is null and not deleted and daily_effort_id is not null;
-- File name search and status filter in the Track File Manager (TFM-01).
create index track_file_name_trgm on gold.track using gin (file_name gin_trgm_ops) where valid_to is null;
create index track_change on gold.track (change_id);

-- The PostGIS copy, rebuilt per track from DuckLake (MAP-06). Not versioned: DuckLake snapshots
-- hold the earlier versions of the points.
create table gold.track_copy (
    track_id              bigint primary key,
    ducklake_snapshot_id  bigint not null,
    point_count           integer not null,
    first_fix             timestamptz,
    last_fix              timestamptz,
    length_nm             numeric(7, 3),
    mean_knots            real,
    top_knots             real,
    suspect               boolean not null,
    misordered_count      integer not null,
    repeated_count        integer not null,
    rebuilt_at            timestamptz not null default now()
);

create table gold.track_copy_point (
    track_id  bigint not null references gold.track_copy on delete cascade,
    seq       integer not null,
    fix_time  timestamptz not null,
    geom      geometry(Point, 4326) not null,
    primary key (track_id, seq)
);
-- Spatial questions over the points, the reason for the copy (Q-072).
create index track_copy_point_geom on gold.track_copy_point using gist (geom);
-- Points in a date range across all tracks; fixes arrive in time order, so BRIN stays small.
create index track_copy_point_time on gold.track_copy_point using brin (fix_time);

create table gold.track_copy_line (
    track_id          bigint not null references gold.track_copy on delete cascade,
    tolerance_m       smallint not null check (tolerance_m in (11, 550)),
    geom              geometry(LineString, 4326) not null,
    fix_times         timestamptz[] not null,
    max_step_seconds  real[] not null,
    max_step_metres   real[] not null,
    max_step_knots    real[] not null,
    primary key (track_id, tolerance_m),
    check (cardinality(fix_times) = ST_NPoints(geom))
);
-- Explore: tracks crossing the map view at the 550 m level (MAP-05, EXPL-02).
create index track_copy_line_explore on gold.track_copy_line using gist (geom) where tolerance_m = 550;

-- Current views: what every page reads ---------------------------------------------------------

create view gold.daily_effort_current as select * from gold.daily_effort where valid_to is null and not deleted;
create view gold.sighting_current as select * from gold.sighting where valid_to is null and not deleted;
create view gold.daily_condition_current as select * from gold.daily_condition where valid_to is null and not deleted;
create view gold.daily_event_current as select * from gold.daily_event where valid_to is null and not deleted;
create view gold.sighting_event_current as select * from gold.sighting_event where valid_to is null and not deleted;
create view gold.other_species_current as select * from gold.other_species where valid_to is null and not deleted;
create view gold.tag_deployment_current as select * from gold.tag_deployment where valid_to is null and not deleted;
create view gold.individual_current as select * from gold.individual where valid_to is null and not deleted;
create view gold.identification_current as select * from gold.identification where valid_to is null and not deleted;
create view gold.sample_current as select * from gold.sample where valid_to is null and not deleted;
create view gold.track_current as select * from gold.track where valid_to is null and not deleted;

-- Every version across tables, for the Audit Log page grouped by change_id (AUD-01 to AUD-03).
create view gold.change_log as
    select 'daily_effort'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.daily_effort
union all
    select 'sighting'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.sighting
union all
    select 'daily_condition'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.daily_condition
union all
    select 'daily_event'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.daily_event
union all
    select 'sighting_event'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.sighting_event
union all
    select 'other_species'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.other_species
union all
    select 'tag_deployment'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.tag_deployment
union all
    select 'individual'::text as record_table, id as record_id, null::integer as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.individual
union all
    select 'identification'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.identification
union all
    select 'sample'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.sample
union all
    select 'track'::text as record_table, id as record_id, legacy_id as legacy_id, version_id, valid_from, valid_to, deleted,
           change_type, change_source, changed_by, pipeline_run_id, change_reason, change_id from gold.track;

-- One effort's day in time order: weather readings, log entries and sightings (EDET-09, TRACK-03, TRACK-08).
create view gold.effort_timeline as
    select daily_effort_id, 'condition'::text as kind, id as record_id, observed_at as at, geom
    from gold.daily_condition_current
    union all
    select daily_effort_id, 'event', id, event_at, geom from gold.daily_event_current
    union all
    select daily_effort_id, 'sighting', id, sighting_date + coalesce(sighting_time, time '00:00'), geom
    from gold.sighting_current;

-- Summaries the lists sort and filter by. Refreshed concurrently after each pipeline load and
-- after each site change to the tables they read.

-- Efforts list: Track pill, Distance, Sightings (EFF-01); EDET-07 distance check; GPS Track filter.
create materialized view gold.effort_summary as
    select e.id as daily_effort_id,
           count(s.id) as sightings,
           coalesce(sum(s.est_size_best), 0) as animals,
           t.id as track_id,
           t.status as track_status,
           c.length_nm as track_length_nm,
           coalesce(c.suspect, false) as track_suspect
    from gold.daily_effort_current e
    left join gold.sighting_current s on s.daily_effort_id = e.id
    left join gold.track_current t on t.daily_effort_id = e.id
    left join gold.track_copy c on c.track_id = t.id
    group by e.id, t.id, t.status, c.length_nm, c.suspect;
create unique index effort_summary_effort on gold.effort_summary (daily_effort_id);
-- Sort the Efforts list by Sightings (EFF-02).
create index effort_summary_sightings on gold.effort_summary (sightings);

-- Individuals list: First Seen, Last Seen, Sightings; Years Seen and Region Seen filters (IND-01, IND-02).
create materialized view gold.individual_summary as
    select i.id as individual_id,
           min(n.seen_on) as first_seen,
           max(n.seen_on) as last_seen,
           count(n.id) as sightings,
           coalesce(array_agg(distinct extract(year from n.seen_on)::integer) filter (where n.seen_on is not null), '{}') as years_seen,
           coalesce(array_agg(distinct n.region) filter (where n.region is not null), '{}') as regions_seen
    from gold.individual_current i
    left join gold.identification_current n on n.individual_id = i.id
    group by i.id;
create unique index individual_summary_individual on gold.individual_summary (individual_id);
-- Default sort Last Seen newest first (IND-03).
create index individual_summary_last_seen on gold.individual_summary (last_seen desc);
-- Years Seen and Region Seen filters (IND-02).
create index individual_summary_years on gold.individual_summary using gin (years_seen);
create index individual_summary_regions on gold.individual_summary using gin (regions_seen);

-- Place names for search and the Region, Sub-Area and Locality filters (SRCH-01, FILT-01).
create materialized view gold.place_name as
    select region, sub_area, locality, count(*) as efforts
    from gold.daily_effort_current
    group by region, sub_area, locality;
create unique index place_name_key on gold.place_name (region, sub_area, locality) nulls not distinct;
-- Locality search with typos (SRCH-02).
create index place_name_locality_trgm on gold.place_name using gin (locality gin_trgm_ops);
