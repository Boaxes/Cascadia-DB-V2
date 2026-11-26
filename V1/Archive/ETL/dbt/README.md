# The data pipeline

This folder builds the database the website reads. It is a
[dbt](https://docs.getdbt.com/) project: a set of SQL files, each one a
`SELECT`, that dbt runs in the right order to make tables and views.

Everything here is SQL. If you can read a `SELECT` with a few `CASE`
expressions and `JOIN`s, you can read and change this pipeline.

## The three schemas

The database has three schemas, and data only ever flows one way through
them:

```
raw  ──────────────►  dbo  ──────────────►  app
DB167 as imported     cleaned, with the      the views the
+ the curated lists   website's edits        website reads
```

- **`raw`** is DB167, copied table for table by `ETL/import_raw.py`, and never
  changed afterwards: a trigger on each table refuses any change. It also holds
  the pipeline's own inputs, which are kept from one build to the next:
  - `raw.species`: species names;
  - `raw.event_code_name`: event code names;
  - `raw.vessel_list`: every vessel spelling ever met, with its id;
  - `raw.track_geometry`: the GPS line of every track file in storage.
- **`dbo`** is the cleaned data. It has one table per DB167 table, with DB167's
  own columns, plus columns DB167 has no room for (points, depths in metres,
  species and vessel ids). Every website edit is applied on top.
- **`app`** is what the website reads: one view per page's worth of data, plus
  `app.audit_log`, the record of every change made on the website.

`dbo` and `app` are rebuilt from scratch every time. **Anything changed in
them directly, in DBeaver or in psql, is lost at the next build.** A change
that should last goes in a file in this folder, as described in
[Making a change](#making-a-change).

## How dbt works, in brief

- **A model is one `.sql` file holding one `SELECT`.** dbt turns it into a
  table or a view named after the file. `models/dbo/SightingT.sql` becomes
  `dbo."SightingT"`.
- **`{{ ref('SightingT') }}` means "the SightingT model".** dbt reads these to
  work out the order to build in. A model that uses `ref('SightingT')` is built
  after `SightingT`. **`{{ source('raw', 'SightingT') }}`** means a table dbt
  doesn't build, here the raw copy of DB167's `SightingT`.
- **Anything between `{{ }}` or `{% %}` is filled in before the SQL runs.**
  That's Jinja, a template language. `{% set x %}...{% endset %}` names a
  piece of SQL so it can be used more than once. `{{ spelled("Species") }}`
  calls a macro: a named piece of SQL kept in `macros/`, used by several
  models. To see the plain SQL a model really runs, compile it (see
  [Reading the SQL dbt runs](#reading-the-sql-dbt-runs)).
- **A test is a `SELECT` that must return no rows.** Each file in `tests/`
  looks for something that should never happen, such as a sighting whose
  species code resolves to no species. Any row it returns is a failure.
- **YAML files describe what SQL can't.** `models/dbo/_dbo.yml` gives every
  `dbo` column its type. Under `config: meta:`, it also gives each table its
  keys, indexes and triggers, and each column its `NOT NULL`, default and
  foreign key. dbt applies these after it builds each table.

### Build, then swap

A build never touches the live `dbo` and `app`:

1. **`dbt build`** makes every table and view in fresh schemas, `dbo_next` and
   `app_next`, and runs every test against them. If all of that succeeds, it
   marks the build complete.
2. **`dbt run-operation swap`** replaces `dbo` and `app` with the finished
   build, in one transaction. The website sees the old data until that moment,
   then the new. The swap refuses if the build isn't complete, or if someone
   has saved an edit on the website since the build started (build again).

A failed build changes nothing the website uses.

## The files

```
dbt_project.yml        settings: which folder builds into which schema
profiles.yml           how to connect to the database
models/
  sources.yml          the tables in raw that dbt reads but doesn't build
  dbo/
    SightingT.sql ...  one file per dbo table
    _dbo.yml           every dbo column's type; keys, indexes, triggers
    views/             DB167's own views, rebuilt in dbo
    replay/            the audit log, read once and used by every dbo table
    lookups/           the vessel lookup, used by every table with a vessel
  app/
    sighting.sql ...   one file per view the website reads
    _app.yml
macros/                SQL shared between models
  cleaning.sql         the cleaning rules used across tables (R1, R2, R7)
  replay.sql           how the website's edits are applied
  lists.sql            species and vessel ids
  structure.sql        keys, indexes and foreign keys from the YAML
  swap.sql             the swap
  compare_build.sql    comparing a build with what is live
tests/                 one file per check
```

## Reading a dbo model

Every file in `models/dbo/` reads the same way, top to bottom. Take
`models/dbo/SightingT.sql`:

1. **The header** lists the cleaning rules the table applies, by name: R1,
   R2, CRD-002 and so on.
2. **`{% set ... %}` blocks** name the longer expressions, such as `depth_m`,
   the depth converted to metres. Each one has a comment saying what it does.
3. **`with t as (...)`** is DB167's table, from `raw`.
4. **`cleaned`** is DB167's rows with the cleaning rules applied, one column
   per line. A line like `t."Date" as "Date"` passes a column through as it
   is. A line with a `case` or a macro in it is where a rule changes that
   column.
5. **`r` and `s`** apply the website's edits: rows it deleted are dropped,
   rows it created are added, and every field it changed takes its newest
   value. You won't need to change these.
6. **The final `select`** is what `dbo."SightingT"` holds: DB167's columns
   (`column_list(...)`), then the columns this table adds, each wrapped in
   `edited(...)`, which lets a website edit win over the worked-out value.

### Reading the SQL dbt runs

To see a model as plain SQL, with every macro filled in:

```
docker compose run --rm etl dbt compile --select SightingT --vars '{"schema_suffix": ""}'
```

It prints the SQL, and saves it in
`ETL/dbt/target/compiled/cascadia/models/dbo/SightingT.sql`. You can paste it
into DBeaver and run it, which is the quickest way to try a change out. The
`--vars` part makes it read the live `dbo` rather than `dbo_next`, which only
exists between a build and its swap.

## The lineage graph

dbt draws which models read which, and serves the drawing, with every
model's code and columns, as a small website on your machine. First, write
the documentation:

```
docker compose run --rm etl dbt docs generate --vars '{"schema_suffix": ""}'
```

The `--vars` part makes it describe the live `dbo` and `app` rather than a
build's `dbo_next` and `app_next`. Then serve it:

```
docker compose run --rm --service-ports etl dbt docs serve --host 0.0.0.0 --port 8080
```

Open **http://localhost:8580** in your browser. Press Ctrl-C in the terminal
to stop it. Run `docs generate` again after changing a model, to see the
change.

On the site:

- **The left-hand list** has every model, under `cascadia`, `models`, `dbo`
  or `app`, and every raw table, under Sources.
- **A model's page** has tabs:
  - Columns: every column and its type;
  - Depends On: what the model reads;
  - Referenced By: what reads it;
  - Code: the model's file, with a Compiled button for the plain SQL.
- **The round button at the bottom right** opens the lineage graph for the
  model you are on. The corner button at its top right makes it full screen.
  Raw tables are green, models blue, and the one you are on red.
- **The `--select` box** under the full-screen graph chooses what is drawn,
  then press Update Graph:
  - `+SightingT+`: SightingT, everything it reads and everything that reads
    it;
  - `+SightingT`: only what it reads, back to raw;
  - `SightingT+`: only what depends on it, out to the website's views.

  Click a box in the graph to open that model.

## Running the pipeline

All of these run in a terminal in the `Cascadia-DB` folder, with
`docker compose up` running in another.

**1. Import DB167**, only when you want DB167's latest data. It replaces
DB167's tables in `raw` and leaves the pipeline's own inputs alone:

```
docker compose run --rm etl python import_raw.py
```

**2. Build**, into `dbo_next` and `app_next`, with every test:

```
docker compose run --rm etl dbt build
```

It takes a few seconds. The last line says `Done.`, with counts. `ERROR=0` and
`FAIL=0` mean the build is complete and can be swapped in. Otherwise, the lines
above say which model or test failed and why. See
[When something fails](#when-something-fails).

**3. Look at what changed**, if you like, before anything goes live:

```
docker compose run --rm etl dbt run-operation compare_build
```

It compares the build with what is live, table by table, and lists every table
and view whose rows or structure differ. To see the rows themselves, query
both schemas in DBeaver, for example:

```sql
select o."SightingID", o.depth_m as live, n.depth_m as built
from dbo."SightingT" o
join dbo_next."SightingT" n using ("SightingID")
where o.depth_m is distinct from n.depth_m;
```

**4. Swap it in:**

```
docker compose run --rm etl dbt run-operation swap
```

The website shows the new data straight away.

**Two builds from the same data must match exactly.** After a swap, build
again and run `compare_build`: it should say "The build matches what is
live." If it doesn't, something depends on the order Postgres happens to read
rows in, and that needs fixing before anything else.

These commands run the pipeline on your machine, against your local copy.
The server doesn't run it yet. Until it does, the live database is left
alone.

## Making a change

The rule: **change a file here, build, look, swap, commit.** Never change
`dbo` or `app` directly. The next build would undo it, and nobody would know
it had happened.

Each change below ends the same way:

```
docker compose run --rm etl dbt build
```

```
docker compose run --rm etl dbt run-operation compare_build
```

Check that `compare_build` lists only the tables you meant to change, and
query them to see the new values. Then:

```
docker compose run --rm etl dbt run-operation swap
```

and commit the change, saying in the message which rows changed and why.

### Fix or merge spellings in a column

Most spelling fixes are a mapping, a list of `'from': 'to'` pairs. They are
matched ignoring case and the spaces around them. In
`models/dbo/DailyEffortT.sql`, the survey type is:

```sql
{{ mapped(spelled("Survey Type"), {'Non-Standardized Large Vessel': 'Large Vessel Non-Standardized',
                                   'Land Observation': 'Land', 'ENTANGLEMENT': 'Entanglement Response',
                                   'ENT': 'Entanglement Response', 'Uknown': 'Unknown'}) }} as "Survey Type",
```

To merge `Land based` into `Land` as well, add `'Land based': 'Land'` to the
list. Add a line to the file's header saying what the rule does. For a
spelling that differs from another only in case, you don't need to do
anything: R1 already folds those into the one each research group uses most.

For a rule that isn't a straight swap of one value for another, write a
`case` expression on that column's line in `cleaned`, as `SampleT.sql` does
for the certainty column:

```sql
case when t."Research Group" = 'CRC' and btrim({{ spelled("Certainty of Sample ID") }}) ~ '^[0-9]+$' then null
     else {{ spelled("Certainty of Sample ID") }} end as "Certainty of Sample ID",
```

The history window explains a change made by cleaning with the rule that
claims that column. So add a row to `models/app/rule_column.sql` with the
rule's name, a sentence saying what it does, the table and the column.

Leave the raw column alone and write the rule in `dbo`. `raw` has to stay
exactly what DB167 said, so the history window can show what a value was
before it was cleaned.

### Correct one record

Edit it on the website. That goes into the audit log under your name, shows
in the record's history, can be undone, and is applied again on every build.
Write a rule only when a whole kind of value is wrong, including rows DB167
hasn't sent yet.

### Add a column to a dbo table

Say sightings should carry the depth in feet as well as metres:

1. In `models/dbo/SightingT.sql`, add it to the final `select`:

   ```sql
   {{ edited('depth_ft', 'round(' ~ depth_m ~ ' / 0.3048, 2)', 'numeric(10,2)', 's.__edits') }} as depth_ft,
   ```

   The first argument to `edited()` is the column's name in the audit log.
   It lets a website edit to that column win over the worked-out value.

2. In `models/dbo/_dbo.yml`, under `SightingT`'s columns, give it a type:

   ```yaml
         - name: "depth_ft"
           quote: true
           data_type: "numeric(10,2)"
   ```

3. For the website to see it, add it to the view in `models/app/sighting.sql`
   (for example `s.depth_ft AS depth_ft`), and to the matching model in
   `Django/survey/models.py`.

### Rename a column

**A column the pipeline adds** (such as `depth_m`, `geom` or `vessel_id`):
change its name after `as` in the final `select`, and in `_dbo.yml`, then
build. The build fails on every view or test that still uses the old name,
which lists exactly what else to update: the `app` view, the tests, and
`Django/survey/models.py`.

**Keep the audit log's name.** Past edits to that column are recorded under
its old name, and the log is never rewritten. So leave the first argument to
`edited()` as the old name, and change only the name after `as`:

```sql
{{ edited('depth_m', depth_m, 'numeric(10,2)', 's.__edits') }} as depth_metres,
```

**A column from DB167** keeps DB167's name in `dbo`, so `dbo` can always be
compared with `raw`. To give it a better name on the website, rename it in the
`app` view, as `app.sighting` already does for many columns:
`s."Start Time" AS sighting_time`.

### Drop a column

**A column the pipeline adds:** delete its line from the final `select` and
from `_dbo.yml`, then build. As with a rename, the build fails on everything
that still uses it, and each failure says where. Remove it from each place
and build again. Edits made to it stay in the audit log. They are simply no
longer applied to anything.

**A column from DB167** stays in `dbo`, for the same reason as above. To stop
the website showing it, leave it out of the `app` view (and out of
`Django/survey/models.py`).

### Change a key, an index or a foreign key

They are in `models/dbo/_dbo.yml`:

- **A table's primary key, unique constraints, indexes and triggers:** under
  the table's `config: meta: structure:`.
- **A column's `not_null`, `default` and `references` (a foreign key):**
  under the column's `config: meta:`.

Copy the form of an entry that is already there. A foreign key that the data
doesn't satisfy fails the build, and the error names the constraint.

### Add a table or view

Add a new `.sql` file to `models/dbo/` or `models/app/`, and an entry for it
in that folder's YAML file. A `dbo` table gets its columns' types and its key.
An `app` view that the website writes through needs
`{{ config(materialized='updatable_view', meta={'check_option': true}) }}`
at the top, as `models/app/sighting.sql` has.

### Change a species name, an event code name or a vessel

These live in `raw.species`, `raw.event_code_name` and `raw.vessel_list`.
Those tables are kept from build to build, so this is the one kind of change
you make with SQL straight into the database:

```sql
update raw.species set common_name = 'Cuvier''s beaked whale' where code = 'Zc';
```

Then build and swap. Never change an id: ids are how records point at a
species or vessel, and the audit log has recorded some of them. A species
code or vessel spelling the data uses but the list doesn't have yet is added
to the list by the swap, with the next id.

## Tests

Every build runs every file in `tests/`. Each one says at the top what it
checks. Together they check that:
- every website edit is in `dbo`;
- no value changed without a cleaning rule or an edit explaining it;
- every point matches its coordinates, and every coordinate pair is whole;
- every species code and vessel text resolves;
- ids in the species and vessel lists never move;
- a track's status follows its link and its file;
- `raw` is still frozen.

A test that fails blocks the swap. Usually that means the change broke
something it shouldn't have, so read the failure and fix the model. A test
can also fail because of data: a new DB167 import, or an edit on the website,
can bring in a value a rule has never seen. Then either fix the record on the
website, or extend the rule to cover it.

To add a check, add a file to `tests/` holding a `SELECT` that returns the
rows that are wrong.

The website has tests of its own, in `TESTS/`. They run through the website's
own code against a copy of your local database: `ops/test.sh reference`. The
ones that rebuild with this pipeline and check that a change survives are
skipped unless `TEST_REBUILD=1` is set.

## When something fails

- **A model fails with an SQL error.** The error names the model and gives
  Postgres's message. Compile the model (see
  [Reading the SQL dbt runs](#reading-the-sql-dbt-runs)) and run the SQL in
  DBeaver to find the line.
- **A test fails.** The message names the test and how many rows it returned.
  Its compiled SQL is in `ETL/dbt/target/compiled/cascadia/tests/`: run it in
  DBeaver to see the rows.
- **The swap says the build did not complete.** Something failed, or only
  part of the project was built (`--select` builds part of it, and a partial
  build is never swapped in). Build everything again.
- **The swap says the audit log has newer entries.** Someone saved an edit on
  the website after the build started. Build again, then swap.
- **The swap says views read from `dbo`.** A view outside `dbo` was made by
  hand, and dropping `dbo` would silently take it with it. Move it into a
  model here instead.

Nothing live changes until a swap succeeds, so a failure never leaves the
website half-updated.
