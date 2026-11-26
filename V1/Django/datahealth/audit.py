"""
Writing to the audit log, and putting a change back.

Every write the application makes goes through here. That is the point: one
place, so nothing can change a record without saying who did it and why.

`target_table` names the `dbo` table and `target_pk` its real key, not the view
the change came in through. The view is how Django reached the row; the table is
where the value lives, which is what somebody looking in pgAdmin will search
for, and what stays meaningful if a view is ever restructured.

A delete keeps the whole row and its dependents in `snapshot`, which is what
makes it undoable. Undoing a change puts the data back exactly as it was and
removes the entry: the log lists what is in effect, not what was tried and
taken back. Changes to one record are undone newest first, so undoing an old
change can never quietly overwrite a newer one.

An entry whose `snapshot` names an `uploaded_object` also put a file in object
storage, and undoing it removes that file again.
"""

import json

from django.db import DatabaseError, connection, transaction

from . import events

# Which dbo table each app view sits on. One-to-one, which is what makes the
# views updatable in the first place.
DBO_TABLE = {
    "sighting": "SightingT",
    "daily_effort": "DailyEffortT",
    "daily_condition": "DailyConditionT",
    "daily_event": "DailyEventT",
    "sample": "SampleT",
    "track": "TrackT",
}

def _json(value):
    """
    Decode a jsonb column read through a raw cursor.

    Django registers a psycopg loader that returns jsonb as the raw JSON text,
    so that its own JSONField can decode it. A cursor query bypasses that.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


def quote(name):
    """A column name for a query that takes parameters. DB167 has names with a
    percent sign in them ("% Cloud Cover"), which the driver would otherwise
    read as the start of a placeholder."""
    return '"' + name.replace('"', '""').replace("%", "%%") + '"'


def _primary_key(table):
    with connection.cursor() as cur:
        cur.execute("""
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = ('dbo.' || quote_ident(%s))::regclass
              AND i.indisprimary
        """, [table])
        return cur.fetchone()[0]


def _references(table):
    """Tables with a foreign key straight at this one: (table, column, key)."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT child.relname, ca.attname, pa.attname
            FROM   pg_constraint c
            JOIN   pg_class child  ON child.oid = c.conrelid
            JOIN   pg_class parent ON parent.oid = c.confrelid
            JOIN   pg_attribute ca ON ca.attrelid = c.conrelid
                                  AND ca.attnum = c.conkey[1]
            JOIN   pg_attribute pa ON pa.attrelid = c.confrelid
                                  AND pa.attnum = c.confkey[1]
            WHERE  c.contype = 'f' AND parent.relname = %s
              AND  child.relnamespace = 'dbo'::regnamespace
              AND  child.relname <> parent.relname
            ORDER  BY child.relname
        """, [table])
        return cur.fetchall()


def _foreign_keys(table):
    """Tables this one points at, of those given: for ordering inserts."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT parent.relname
            FROM   pg_constraint c
            JOIN   pg_class child  ON child.oid = c.conrelid
            JOIN   pg_class parent ON parent.oid = c.confrelid
            WHERE  c.contype = 'f' AND child.relname = %s
              AND  parent.relnamespace = 'dbo'::regnamespace
        """, [table])
        return {r[0] for r in cur.fetchall()}


def collect(table, key_column, key_value):
    """
    One row and everything that would have to go with it.

    Returns ({table: [rows]}, [table order for inserting]). Delete in the
    reverse of that order.

    The shape is a graph rather than a tree: SightingIdentificationT points at
    both SightingT and IdentificationT, so a plain depth-first walk visits it
    twice and gets the order wrong. Rows are therefore gathered by table and
    de-duplicated on their own key, and the order is worked out afterwards from
    which table points at which.
    """
    gathered = {}          # table -> {pk: row}
    queue = [(table, key_column, key_value)]
    with connection.cursor() as cur:
        while queue:
            parent, column, value = queue.pop()
            for child, child_column, parent_column in _references(parent):
                if parent_column != column:
                    continue
                cur.execute(
                    f'SELECT to_jsonb(t) FROM dbo."{child}" t WHERE "{child_column}" = %s',
                    [value])
                child_key = _primary_key(child)
                for row in (_json(r[0]) for r in cur.fetchall()):
                    holder = gathered.setdefault(child, {})
                    if row[child_key] in holder:
                        continue
                    holder[row[child_key]] = row
                    queue.append((child, child_key, row[child_key]))

    rows = {name: list(bykey.values()) for name, bykey in gathered.items()}

    # Parents before children, so every insert has something to point at.
    order, placed = [], set()
    remaining = set(rows)
    while remaining:
        ready = sorted(t for t in remaining
                       if not (_foreign_keys(t) & remaining) - {t})
        if not ready:                       # a cycle: fall back to any order
            ready = sorted(remaining)
        for name in ready:
            order.append(name)
            placed.add(name)
        remaining -= placed
    return rows, order


def _legacy_pk(cur, table, pk, snapshot):
    """
    DB167's own ID of the record, for the tables with a hashed key, so the
    pipeline can still find the record if DB167 changes one of its key columns
    and its id with it. A deleted record's is in the snapshot; any other is
    read from the record itself, which is still there when this runs.
    """
    legacy = LEGACY_ID.get(table)
    if legacy is None or pk is None:
        return None
    kept = (snapshot or {}).get(table)
    if isinstance(kept, list) and kept:
        value = kept[0].get(legacy)
    else:
        cur.execute(f'SELECT {quote(legacy)} FROM dbo."{table}" WHERE {quote(_primary_key(table))}::text = %s',
                    [str(pk)])
        row = cur.fetchone()
        value = row[0] if row else None
    return None if value is None else str(value)


def record(actor, action, table, pk, changes=None, snapshot=None, comment=None):
    """Write one entry. Returns its id."""
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO app.audit_log
                (actor_id, actor_name, action, target_table, target_pk,
                 legacy_pk, changes, snapshot, comment)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, [
            getattr(actor, "id", None),
            getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "unknown"),
            action, table, str(pk),
            _legacy_pk(cur, table, pk, snapshot),
            json.dumps(changes, default=str) if changes else None,   # dates and times as text
            json.dumps(snapshot, default=str) if snapshot else None,
            comment,
        ])
        entry_id = cur.fetchone()[0]
        _check_against_db167(entry_id)
    # The server event log says it too, so one page shows everything the server did.
    events.record("audit", action, user=actor, message=f"{table} {pk}" + (f": {comment}" if comment else ""),
                  audit_id=entry_id, table=table, record=str(pk), fields=sorted((changes or {}).keys()))
    return entry_id


def _check_against_db167(entry_id):
    """
    Say whether DB167 holds the change just logged, which it does not yet, or
    never will if it is a file upload. The pipeline checks every entry again
    after each build (ETL/dbt/macros/db167_state.sql); until the first build
    that makes the check, the entry stays pending.
    """
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SELECT app.refresh_db167_state(%s)", [entry_id])
    except DatabaseError:
        pass


def update(actor, view_name, pk, values, comment=None, action="update",
           uploaded_object=None, extra_changes=None, snapshot=None):
    """
    Change some fields of one record, reading the old values first so the log
    can say what they were. `action` names the change for the log (associate,
    upload, edit_file); every kind is undone the same way, by writing the old
    values back.

    `extra_changes` are things the entry says that are not columns of the
    record (the file version an edit_file kept), and `snapshot` what undoing it
    needs besides the old values; neither is written to the table.
    """
    table = DBO_TABLE[view_name]
    key = _primary_key(table)
    columns = list(values)
    with transaction.atomic(), connection.cursor() as cur:
        selected = ", ".join(quote(c) for c in columns)
        cur.execute(f'SELECT {selected} FROM dbo."{table}" WHERE "{key}" = %s', [pk])
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"{table} {pk} does not exist")
        before = dict(zip(columns, row))

        assignments = ", ".join(quote(c) + " = %s" for c in columns)
        cur.execute(f'UPDATE dbo."{table}" SET {assignments} WHERE "{key}" = %s',
                    [values[c] for c in columns] + [pk])

        changes = {c: {"old": before[c], "new": values[c]}
                   for c in columns if before[c] != values[c]}
        changes.update(extra_changes or {})
        if not changes:
            return None
        kept = dict(snapshot or {})
        if uploaded_object:
            kept["uploaded_object"] = uploaded_object
        return record(actor, action, table, pk, changes=changes, comment=comment,
                      snapshot=kept or None)


def delete(actor, view_name, pk, comment=None, extra_snapshot=None):
    """
    Remove one record, keeping it and everything hanging off it so it can come
    back. The dependents go first, because the foreign keys are real.
    `extra_snapshot` is what putting it back needs besides rows: a track's
    geometry row, and where its file was moved to.
    """
    table = DBO_TABLE[view_name]
    key = _primary_key(table)
    snapshot = {}
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f'SELECT to_jsonb(t) FROM dbo."{table}" t WHERE "{key}" = %s', [pk])
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"{table} {pk} does not exist")
        snapshot[table] = [_json(row[0])]

        rows, order = collect(table, key, pk)
        snapshot.update(rows)
        snapshot["__order__"] = order
        snapshot.update(extra_snapshot or {})
        # Children before parents, so nothing is left pointing at a row that has
        # gone. The foreign keys would refuse it anyway.
        for name in reversed(order):
            child_key = _primary_key(name)
            cur.execute(
                f'DELETE FROM dbo."{name}" WHERE "{child_key}" = ANY(%s)',
                [[r[child_key] for r in rows[name]]])
        cur.execute(f'DELETE FROM dbo."{table}" WHERE "{key}" = %s', [pk])

        return record(actor, "delete", table, pk, snapshot=snapshot, comment=comment)


def insert(actor, view_name, values, comment=None, uploaded_object=None):
    """
    Add one record. Undone by deleting it again, so the new row's values are
    kept as the entry's changes (old: nothing, new: what was written).
    """
    table = DBO_TABLE[view_name]
    key = _primary_key(table)
    columns = list(values)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            f'INSERT INTO dbo."{table}" ({", ".join(quote(c) for c in columns)}) '
            f'VALUES ({", ".join(["%s"] * len(columns))}) RETURNING {quote(key)}',
            [values[c] for c in columns])
        pk = cur.fetchone()[0]
        return pk, record(actor, "create", table, pk,
                          changes={c: {"old": None, "new": values[c]} for c in columns},
                          snapshot={"uploaded_object": uploaded_object} if uploaded_object else None,
                          comment=comment)


# What an entry says that is not a column of the record, so undoing it leaves
# it alone: edit_file's kept version.
NOT_COLUMNS = ("version",)


def undoable(entry):
    """Why an entry cannot be undone, or None when it can."""
    if entry["action"] not in ("update", "associate", "dissociate", "upload", "edit_file",
                               "delete", "create"):
        return "This kind of entry is a record of something, not a change to put back."
    if entry.get("restored_by"):
        return "Already restored."
    return None


def _reinsert(cur, table, snapshot):
    """Put a deleted record back, with its dependents."""
    # The record first, then its dependents shallowest first, so every child
    # has a parent by the time it is inserted.
    for name in [table] + snapshot.get("__order__", []):
        for values in snapshot.get(name, []):
            columns = list(values)
            names = ", ".join(quote(c) for c in columns)
            marks, params = [], []
            for column in columns:
                value = values[column]
                if isinstance(value, (dict, list)):
                    # PostGIS renders a geometry as GeoJSON inside
                    # to_jsonb, so it has to be read back as geometry
                    # rather than handed over as an object.
                    marks.append("ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)")
                    params.append(json.dumps(value))
                else:
                    marks.append("%s")
                    params.append(value)
            cur.execute(
                f'INSERT INTO dbo."{name}" ({names}) '
                f'VALUES ({", ".join(marks)})', params)


def _put_back_geometry(cur, row):
    """A file's row in app.track_geometry as it was, kept in a snapshot."""
    cur.execute("""
        INSERT INTO app.track_geometry
               (object_key, etag, geom, point_count, length_nm, built_at, track_id, first_time, last_time)
        VALUES (%s, %s, ST_GeomFromEWKT(%s), %s, %s, %s, %s, %s, %s)
        ON CONFLICT (object_key) DO UPDATE
           SET etag = EXCLUDED.etag, geom = EXCLUDED.geom,
               point_count = EXCLUDED.point_count, length_nm = EXCLUDED.length_nm,
               built_at = EXCLUDED.built_at, track_id = EXCLUDED.track_id,
               first_time = EXCLUDED.first_time, last_time = EXCLUDED.last_time
    """, [row["object_key"], row["etag"], row["geom"], row["point_count"], row["length_nm"],
          row["built_at"], row["track_id"], row.get("first_time"), row.get("last_time")])


def _check_track_rule(table, pk, changes, snapshot, action):
    """An Effort has one track file at most, so a track that would go back on an
    Effort (an unmatch undone, a deleted track put back) is checked first."""
    if table != "TrackT":
        return
    if action == "delete":
        effort = ((snapshot or {}).get("TrackT") or [{}])[0].get("daily_effort_id")
    else:
        effort = (changes.get("daily_effort_id") or {}).get("old")
    if effort is not None:
        from . import trackfix
        trackfix.check_put_back(effort, pk)


def storage_steps(entry_id):
    """
    What putting an entry back needs done to object storage after the database
    is back: {"restore_version": ...} or {"restore_deleted": ...}, or {}.
    Read before undo() or restore(), which remove or change the entry. The
    caller runs them (gps/tracks.py, restore_storage).
    """
    with connection.cursor() as cur:
        cur.execute("SELECT snapshot FROM app.audit_log WHERE id = %s", [entry_id])
        row = cur.fetchone()
    return (_json(row[0]) if row else {}).get("storage", {})


def undo(entry_id):
    """
    Put the data back as it was before one entry, then remove the entry.

    Returns the object key of a file to remove from storage, if the change
    uploaded one; the caller removes it once the database has committed, so a
    failure there never leaves the data half put back. Any other change to the
    file (storage_steps) is the caller's too.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT action, target_table, target_pk, changes, snapshot, restored_by
            FROM app.audit_log WHERE id = %s FOR UPDATE
        """, [entry_id])
        row = cur.fetchone()
        if row is None:
            raise LookupError("That entry is no longer in the log.")
        action, table, pk, changes, snapshot, restored_by = row
        changes, snapshot = _json(changes), _json(snapshot)
        reason = undoable({"action": action, "restored_by": restored_by})
        if reason:
            raise ValueError(reason)

        cur.execute("""
            SELECT id FROM app.audit_log
            WHERE target_table = %s AND target_pk = %s AND id > %s
            ORDER BY id LIMIT 1
        """, [table, pk, entry_id])
        later = cur.fetchone()
        if later:
            raise ValueError(f"Entry {later[0]} changed this record afterwards. "
                             "Undo that one first.")

        _check_track_rule(table, pk, changes, snapshot, action)
        key = _primary_key(table)
        columns = [c for c in changes if c not in NOT_COLUMNS]
        if action in ("update", "associate", "dissociate", "upload", "edit_file") and columns:
            assignments = ", ".join(quote(c) + " = %s" for c in columns)
            cur.execute(f'UPDATE dbo."{table}" SET {assignments} WHERE "{key}" = %s',
                        [changes[c]["old"] for c in columns] + [pk])
        elif action == "create":
            cur.execute(f'DELETE FROM dbo."{table}" WHERE "{key}" = %s', [pk])
        elif action == "delete":
            _reinsert(cur, table, snapshot)

        # A track's line goes back with the track: the row it had, if the
        # change or the delete kept it.
        if snapshot.get("track_geometry"):
            _put_back_geometry(cur, snapshot["track_geometry"])

        uploaded = (snapshot or {}).get("uploaded_object")
        if uploaded:
            # The file is about to leave storage, so its line goes with it: a
            # geometry row is what says a file is stored.
            cur.execute("DELETE FROM app.track_geometry WHERE object_key = %s", [uploaded])
        cur.execute("DELETE FROM app.audit_log WHERE id = %s", [entry_id])
        return uploaded


# Whether DB167 holds a change (app.audit_log.db167_state), with how the pages
# say so. The pipeline works the state out against DB167 as it was imported.
DB167_STATES = {
    "pending": ("Pending", "DB167 does not hold this change yet."),
    "applied": ("Applied", "DB167 holds this change."),
    "conflict": ("Conflict", "DB167 holds something else, so the migration script skips this change."),
    "not_applicable": ("Not Applicable", "There is nothing for DB167 to hold: a file upload or edit, "
                                          "or a value the website works out itself."),
}


def restore(actor, entry_id):
    """
    Bring a deleted record back, as an entry of its own. The delete stays in
    the log, marked as put back, and the new `restore` entry says who did it.
    The two cancel out when the pipeline replays the log.

    Returns the id of the new entry. A file the delete moved is the caller's to
    move back (storage_steps, read first).
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("""
            SELECT action, target_table, target_pk, snapshot, restored_by, comment
            FROM app.audit_log WHERE id = %s FOR UPDATE
        """, [entry_id])
        row = cur.fetchone()
        if row is None:
            raise LookupError("That entry is no longer in the log.")
        action, table, pk, snapshot, restored_by, was = row
        if action != "delete":
            raise ValueError("Only a deleted record can be restored.")
        if restored_by:
            raise ValueError("Already restored.")
        snapshot = _json(snapshot)
        _check_track_rule(table, pk, {}, snapshot, action)
        key = _primary_key(table)
        cur.execute(f'SELECT 1 FROM dbo."{table}" WHERE "{key}"::text = %s', [pk])
        if cur.fetchone():
            raise ValueError("That record is already back.")
        _reinsert(cur, table, snapshot)
        if snapshot.get("track_geometry"):
            _put_back_geometry(cur, snapshot["track_geometry"])
        restored = record(actor, "restore", table, pk,
                          comment=f"Restored: {was}" if was else "Restored.")
        cur.execute("UPDATE app.audit_log SET restored_by = %s WHERE id = %s", [restored, entry_id])
        return restored


def deleted(table):
    """Records of one table deleted and not restored, newest first, each with
    the snapshot its delete kept."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT id, occurred_at, actor_name, target_pk, snapshot, comment
            FROM   app.audit_log
            WHERE  action = 'delete' AND target_table = %s AND restored_by IS NULL
            ORDER  BY id DESC
        """, [table])
        return [{"id": r[0], "at": r[1], "actor": r[2], "pk": r[3], "snapshot": _json(r[4]),
                 "comment": r[5]} for r in cur.fetchall()]


def for_record(table, pk):
    """The entries about one record, newest first: its history."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT id, occurred_at, actor_name, action, changes, comment, restored_by
            FROM   app.audit_log WHERE target_table = %s AND target_pk = %s
            ORDER  BY id DESC
        """, [table, str(pk)])
        return [{"id": r[0], "at": r[1], "actor": r[2], "action": r[3],
                 "changes": _json(r[4]), "comment": r[5], "restored_by": r[6]}
                for r in cur.fetchall()]



# The tables whose Primary Key in dbo is a hashed id, and the DB167 ID column
# people know their records by. target_pk holds the hashed id; pages show and
# search by DB167's.
LEGACY_ID = {
    "DailyEffortT": "DailyEffortID", "DailyEventT": "DailyEventID", "DailyConditionT": "DailyConditionID",
    "SightingT": "SightingID", "SightingEventT": "SightingEventID", "OtherSpeciesT": "OtherSpeciesID",
    "SampleT": "SampleID", "IdentificationT": "IdentificationID",
}


def numbers(pairs):
    """{(table, target_pk): the number people know the record by}: DB167's ID
    for the tables with a hashed key, the key itself for the rest."""
    out, wanted = {}, {}
    for table, pk in pairs:
        if table in LEGACY_ID and pk:
            wanted.setdefault(table, set()).add(pk)
        else:
            out[(table, pk)] = pk
    with connection.cursor() as cur:
        for table, pks in wanted.items():
            legacy = LEGACY_ID[table]
            cur.execute(f'SELECT id::text, "{legacy}" FROM dbo."{table}" WHERE id::text = ANY(%s)', [list(pks)])
            found = dict(cur.fetchall())
            missing = [pk for pk in pks if pk not in found]
            if missing:
                # A record that is gone: the copy its delete kept, or the
                # build's own list of every record DB167 had.
                cur.execute("""SELECT target_pk, snapshot -> target_table -> 0 ->> %s FROM app.audit_log
                               WHERE target_table = %s AND target_pk = ANY(%s) AND action = 'delete'""",
                            [legacy, table, missing])
                found.update({pk: number for pk, number in cur.fetchall() if number})
            missing = [pk for pk in pks if pk not in found]
            if missing:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", [f'build."keyed_{table}"'])
                if cur.fetchone()[0]:
                    cur.execute(f'SELECT id::text, "{legacy}" FROM build."keyed_{table}" WHERE id::text = ANY(%s)',
                                [missing])
                    found.update(dict(cur.fetchall()))
            for pk in pks:
                out[(table, pk)] = found.get(pk, pk)
    return out


def entries(limit=200, offset=0, actor=None, table=None, action=None,
            target=None, db167=None):
    """The log, newest first."""
    where, params = ["1 = 1"], []
    if target:
        # The number typed is DB167's ID, or the key itself.
        found = " UNION ALL ".join(f'SELECT id::text FROM dbo."{t}" WHERE "{c}"::text = %s'
                                   for t, c in LEGACY_ID.items())
        where.append(f"(target_pk = %s OR target_pk IN ({found}))")
        params += [str(target)] * (1 + len(LEGACY_ID))
    if actor:
        where.append("actor_name = %s"); params.append(actor)
    if table:
        where.append("target_table = %s"); params.append(table)
    if action:
        where.append("action = %s"); params.append(action)
    if db167:
        where.append("db167_state = %s"); params.append(db167)
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT id, occurred_at, actor_name, action, target_table, target_pk,
                   changes, comment, restored_by, snapshot IS NOT NULL, db167_state
            FROM   app.audit_log WHERE {" AND ".join(where)}
            ORDER  BY occurred_at DESC, id DESC LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = [{
            "id": r[0], "at": r[1], "actor": r[2], "action": r[3],
            "table": r[4], "pk": r[5], "changes": _json(r[6]), "comment": r[7],
            "restored_by": r[8], "has_snapshot": r[9], "db167": r[10],
        } for r in cur.fetchall()]
        known = numbers((r["table"], r["pk"]) for r in rows)
        for r in rows:
            r["number"] = known.get((r["table"], r["pk"]), r["pk"])
        cur.execute(f"SELECT count(*) FROM app.audit_log WHERE {' AND '.join(where)}", params)
        total = cur.fetchone()[0]
    return rows, total


def entry(entry_id):
    """One entry, with enough detail to say what putting it back would do."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT id, occurred_at, actor_name, action, target_table, target_pk,
                   changes, comment, restored_by, snapshot, db167_state, db167_checked_at, db167_fields
            FROM   app.audit_log WHERE id = %s
        """, [entry_id])
        row = cur.fetchone()
    if row is None:
        return None
    snapshot = _json(row[9])
    counts = [(name, len(rows)) for name, rows in snapshot.items()
              if isinstance(rows, list) and name != "__order__"] if snapshot else []
    number = numbers([(row[4], row[5])]).get((row[4], row[5]))
    if number is None and snapshot and row[4] in LEGACY_ID:
        # A deleted record: its DB167 ID is in what the delete kept.
        kept = snapshot.get(row[4]) or [{}]
        number = kept[0].get(LEGACY_ID[row[4]])
    return {
        "id": row[0], "at": row[1], "actor": row[2], "action": row[3],
        "target_table": row[4], "target_pk": row[5], "number": number or row[5], "changes": _json(row[6]),
        "comment": row[7], "restored_by": row[8], "db167": row[10], "db167_checked_at": row[11],
        "db167_fields": _json(row[12]),
        "snapshot_counts": sorted(counts, key=lambda c: -c[1]),
    }


def facets():
    """The distinct actors, tables and actions, for the filters."""
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT actor_name FROM app.audit_log ORDER BY 1")
        actors = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT target_table FROM app.audit_log ORDER BY 1")
        tables = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT action FROM app.audit_log ORDER BY 1")
        actions = [r[0] for r in cur.fetchall()]
    return actors, tables, actions
