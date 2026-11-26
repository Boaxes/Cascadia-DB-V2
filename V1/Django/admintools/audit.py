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

from django.db import connection, transaction

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


def record(actor, action, table, pk, changes=None, snapshot=None, comment=None):
    """Write one entry. Returns its id."""
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO app.audit_log
                (actor_id, actor_name, action, target_table, target_pk,
                 changes, snapshot, comment)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, [
            getattr(actor, "id", None),
            getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "unknown"),
            action, table, str(pk),
            json.dumps(changes, default=str) if changes else None,   # dates and times as text
            json.dumps(snapshot, default=str) if snapshot else None,
            comment,
        ])
        return cur.fetchone()[0]


def update(actor, view_name, pk, values, comment=None, action="update",
           uploaded_object=None):
    """
    Change some fields of one record, reading the old values first so the log
    can say what they were. `action` names the change for the log (associate,
    upload); every kind is undone the same way, by writing the old values back.
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
        if not changes:
            return None
        return record(actor, action, table, pk, changes=changes, comment=comment,
                      snapshot={"uploaded_object": uploaded_object} if uploaded_object else None)


def delete(actor, view_name, pk, comment=None):
    """
    Remove one record, keeping it and everything hanging off it so it can come
    back. The dependents go first, because the foreign keys are real.
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


def undoable(entry):
    """Why an entry cannot be undone, or None when it can."""
    if entry["action"] not in ("update", "associate", "dissociate", "upload", "delete", "create"):
        return "This kind of entry is a record of something, not a change to put back."
    if entry.get("restored_by"):
        return "Already put back through the old Restore."
    return None


def undo(entry_id):
    """
    Put the data back as it was before one entry, then remove the entry.

    Returns the object key of a file to remove from storage, if the change
    uploaded one; the caller removes it once the database has committed, so a
    failure there never leaves the data half put back.
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

        key = _primary_key(table)
        if action in ("update", "associate", "dissociate", "upload") and changes:
            columns = list(changes)
            assignments = ", ".join(quote(c) + " = %s" for c in columns)
            cur.execute(f'UPDATE dbo."{table}" SET {assignments} WHERE "{key}" = %s',
                        [changes[c]["old"] for c in columns] + [pk])
        elif action == "create":
            cur.execute(f'DELETE FROM dbo."{table}" WHERE "{key}" = %s', [pk])
        elif action == "delete":
            # The record first, then its dependents shallowest first, so every
            # child has a parent by the time it is inserted.
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

        uploaded = (snapshot or {}).get("uploaded_object")
        if uploaded:
            # The file is about to leave storage, so its line goes with it: a
            # geometry row is what says a file is stored.
            cur.execute("DELETE FROM raw.track_geometry WHERE object_key = %s", [uploaded])
        cur.execute("DELETE FROM app.audit_log WHERE id = %s", [entry_id])
        return uploaded


LEGACY_ACTOR = "legacy-cleanup"


def entries(limit=200, offset=0, actor=None, table=None, action=None,
            legacy=False, target=None):
    """The log, newest first. The import's own corrections only when asked."""
    where, params = ["1 = 1"], []
    if not legacy:
        where.append("actor_name <> %s"); params.append(LEGACY_ACTOR)
    if target:
        where.append("target_pk = %s"); params.append(str(target))
    if actor:
        where.append("actor_name = %s"); params.append(actor)
    if table:
        where.append("target_table = %s"); params.append(table)
    if action:
        where.append("action = %s"); params.append(action)
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT id, occurred_at, actor_name, action, target_table, target_pk,
                   changes, comment, restored_by, snapshot IS NOT NULL
            FROM   app.audit_log WHERE {" AND ".join(where)}
            ORDER  BY occurred_at DESC, id DESC LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = [{
            "id": r[0], "at": r[1], "actor": r[2], "action": r[3],
            "table": r[4], "pk": r[5], "changes": _json(r[6]), "comment": r[7],
            "restored_by": r[8], "has_snapshot": r[9],
        } for r in cur.fetchall()]
        cur.execute(f"SELECT count(*) FROM app.audit_log WHERE {' AND '.join(where)}", params)
        total = cur.fetchone()[0]
    return rows, total


def entry(entry_id):
    """One entry, with enough detail to say what putting it back would do."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT id, occurred_at, actor_name, action, target_table, target_pk,
                   changes, comment, restored_by, snapshot
            FROM   app.audit_log WHERE id = %s
        """, [entry_id])
        row = cur.fetchone()
    if row is None:
        return None
    snapshot = _json(row[9])
    counts = [(name, len(rows)) for name, rows in snapshot.items()
              if isinstance(rows, list) and name != "__order__"] if snapshot else []
    return {
        "id": row[0], "at": row[1], "actor": row[2], "action": row[3],
        "target_table": row[4], "target_pk": row[5], "changes": _json(row[6]),
        "comment": row[7], "restored_by": row[8],
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
