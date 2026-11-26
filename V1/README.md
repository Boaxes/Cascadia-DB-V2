# Sightings and Effort Explorer

Cascadia Research Collective's marine mammal survey records, 2001 to 2026.

Live at **http://143.198.155.64/**

## What you need installed

[Docker Desktop](https://www.docker.com/products/docker-desktop/), and nothing
else. Everything the application needs is inside the containers. Start Docker
Desktop and leave it running before you do anything below.

**On Windows**, run everything below in **Git Bash**, which comes with
[Git for Windows](https://git-scm.com/download/win). Right-click the
`Cascadia-DB` folder and choose "Open Git Bash here". PowerShell and the old
Command Prompt cannot run the `ops/` scripts.

## Starting it up

Open a terminal in the `Cascadia-DB` folder and run:

```
cp .env.example .env
```

You only ever do that once. Then, still in the `Cascadia-DB` folder, run:

```
docker compose up
```

The first time takes a few minutes while it builds. Leave that terminal alone
now, with the application running in it.

## Loading the data, if necessary

A machine that has never run this before has an empty database, so there is
nothing to look at and no login to use. If that is you, or if the data looks
old, open a **second** terminal in the `Cascadia-DB` folder and run:

```
ops/pull-db.sh
```

It asks for the database password, which is the same one you would use in
DBeaver. Nothing is typed back as you type it.

On Windows, if that fails because `docker compose` is not found in Git Bash,
run the PowerShell version from PowerShell instead. It does the same thing:

```
powershell -ExecutionPolicy Bypass -File ops\pull-db.ps1
```

That copies the live database onto your machine, which takes about a minute. It
wipes your local copy and replaces it, so keep nothing on your machine you care
about. It never writes anything to the server.

## Signing in

Open **http://localhost:8000** in your browser and sign in with your usual
login. It is the same username and password as the live site, because the copy
you just pulled brought the logins with it.

If signing in shows a page saying the local database is empty, the pull above
has not been run on this machine, or did not finish. Run `ops/pull-db.sh`
again and read what it prints: if a step fails, it says which one and why.

## A change, start to finish

This is a real change that was made to the project, as a worked example of the
whole loop. The Edit and Delete buttons used to sit at the very bottom of a
sighting page, under everything else. They were moved to the top right, beside
the title. It is the last commit in this repository's history, so you can look
at it directly.

### Getting up to date

In a second terminal, in the `Cascadia-DB` folder:

```
git pull
```

### Changing the page

`Django/templates/survey/sighting_detail.html` had the heading near the top:

```html
<h1 style="margin-bottom:4px">Sighting {{ sighting.legacy_sighting_id }}</h1>
<p class="muted" style="margin:0 0 18px">
  {{ sighting.species|default:"Species not identified" }}
</p>
```

and the buttons on their own, far down at the bottom of the file:

```html
<div class="record-actions">
  <a class="btn btn-primary" href="/sightings/{{ sighting.legacy_sighting_id }}/edit/">Edit this sighting</a>
  <a class="btn btn-danger" href="/sightings/{{ sighting.legacy_sighting_id }}/delete/">Delete</a>
</div>
```

That block was deleted from the bottom, and the heading and the buttons were
wrapped together in one `<div>` so they share a row:

```html
<div class="detail-head">
  <div>
    <h1 style="margin-bottom:4px">Sighting {{ sighting.legacy_sighting_id }}</h1>
    <p class="muted" style="margin:0">
      {{ sighting.species|default:"Species not identified" }}
    </p>
  </div>
  <div class="record-actions">
    <a class="btn btn-primary" href="/sightings/{{ sighting.legacy_sighting_id }}/edit/">Edit</a>
    <a class="btn btn-danger" href="/sightings/{{ sighting.legacy_sighting_id }}/delete/">Delete</a>
  </div>
</div>
```

### Making it sit on the right

On its own that put the buttons underneath the title rather than beside it, so
this went at the bottom of `Django/static/survey/app.css`:

```css
/* Title on the left, Edit and Delete on the right. */
.detail-head { display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
.detail-head .record-actions { margin: 0; flex-shrink: 0; }
```

`display: flex` puts the two halves side by side, and
`justify-content: space-between` pushes them to opposite ends.

### Checking it

**http://localhost:8000/sightings/114893/** in the browser, refreshed. Nothing
needed restarting, because the application reloads as files are saved. Both
buttons were clicked to check they still went to the right pages.

The same thing was then done to
`Django/templates/survey/effort_detail.html`, so effort pages match.

### Pushing it

In the second terminal, in the `Cascadia-DB` folder:

```
git add -A
```

```
git commit -m "Move Edit and Delete to the top of a record"
```

```
git push
```

That last command put it live. GitHub copied the application to the server and
restarted it, which took about a minute. The Actions tab on GitHub shows a tick
when it has finished, and the change was then on **http://143.198.155.64/**.

## The data pipeline

The website's data is built from DB167 by the SQL files in `ETL/dbt/`. That's
where cleaning rules live, and where a change to a table or a column goes, so
that it lasts: anything changed directly in the database is lost at the next
rebuild. **[ETL/dbt/README.md](ETL/dbt/README.md)** explains the files, how to
open the lineage graph, how to run the pipeline, and how to make each kind of
change (fix a spelling, add, rename or drop a column).

The website's own tests check that every change made on the website survives
a rebuild. With `docker compose up` running, and after running
`ops/make-reference.sh` once:

```
docker compose exec web python manage.py test
```

## Two things to know

If you change `requirements.txt`, a `Dockerfile` or `.env`, press Ctrl-C in the
first terminal and start it again with `docker compose up --build`. Those are
read when the container is created, so a plain restart will not pick them up.

Nothing you do here can damage the live data. Deploying only replaces the
application. The only thing that changes data is using the website itself, and
everything done that way is in the audit log and can be undone.
