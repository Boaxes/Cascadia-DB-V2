"""
The history of one record: what DB167 said, what cleaning made of it, and every
edit since.

Three sources, in order:

  raw.<Table>      the frozen DB167 snapshot, as imported
  dbo.<Table>      the live row
  app.audit_log    every edit, with the old and new value of each field

The middle step -- the value after cleaning but before anyone edited it -- is not
stored anywhere, because `dbo` is live: once someone edits a field, `dbo` holds
their value, not the cleaning result. It is reconstructed instead, by taking the
current value and un-applying each audit entry newest first. That is exact, and
costs nothing, because almost no field is ever edited.

A field nobody has touched has no audit entries, so the chain is just the two
ends and the page says so.
"""

import json
from collections import OrderedDict

from django.db import connection

# The app views are one-to-one with the tables underneath them, which is what
# lets the audit log record where a value actually lives rather than which view
# happened to be on screen.
DBO_TABLE = {
    "sighting": "SightingT",
    "daily_effort": "DailyEffortT",
    "daily_condition": "DailyConditionT",
    "daily_event": "DailyEventT",
    "sample": "SampleT",
    "track": "TrackT",
}


class Step:
    """One link in a field's chain."""

    def __init__(self, value, source, detail=None, actor=None, at=None,
                 comment=None, audit_id=None, restorable=False):
        self.value = value
        self.source = source          # 'original' | 'rule' | 'edit'
        self.detail = detail          # the rule's description, or None
        self.actor = actor
        self.at = at
        self.comment = comment
        self.audit_id = audit_id
        self.restorable = restorable

    @property
    def is_empty(self):
        return self.value is None or self.value == ""


class FieldHistory:
    def __init__(self, field, steps, label=None):
        self.field = field
        self.label = label or field
        self.steps = steps

    @property
    def was_edited(self):
        return any(s.source == "edit" for s in self.steps)


def _json(value):
    """
    Decode a jsonb column read through a raw cursor.

    Django registers a psycopg loader that returns jsonb as the raw JSON text,
    so that its own JSONField can decode it. A cursor query bypasses that.
    """
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


# The same names the edit form uses, so a column reads the same way wherever it
# appears. Anything not listed keeps its own name.
LABELS = {}
for _spec in ("sighting", "daily_effort"):
    try:
        from .editing import FIELDS as _FIELDS
        LABELS.update({f.column: f.label for f in _FIELDS[_spec]})
    except Exception:      # editing imports the audit module; never fail a page
        pass


def _text(value):
    """
    One representation for both sources.

    record_diff returns every value as text, because it walks a jsonb object of
    the whole row. audit_log stores each value with its own JSON type, so a
    number comes back as a float. Comparing the two directly makes -188.5365
    look different from "-188.5365", which put a "nothing changed here"
    cleaning step on the page.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _rule_columns(table):
    with connection.cursor() as cur:
        cur.execute("""
            SELECT column_name, rule_id, description
            FROM   app.rule_column WHERE target_table = %s
        """, [table])
        claimed = {}
        for column, rule_id, description in cur.fetchall():
            # More than one rule can touch a column -- Species is both
            # case-folded and mapped through the synonym list -- so the panel
            # names all of them rather than picking one and being wrong.
            claimed.setdefault(column, []).append(f"{rule_id} — {description}")
        return claimed


def _audit_rows(table, pk):
    with connection.cursor() as cur:
        cur.execute("""
            SELECT id, occurred_at, actor_name, action, changes, comment, restored_by
            FROM   app.audit_log
            WHERE  target_table = %s AND target_pk = %s
            ORDER  BY occurred_at, id
        """, [table, str(pk)])
        return [
            {"id": r[0], "at": r[1], "actor": r[2], "action": r[3],
             "changes": _json(r[4]), "comment": r[5], "restored_by": r[6]}
            for r in cur.fetchall()
        ]


def _raw_values(table, pk, fields):
    """
    What the original database holds for particular fields.

    record_diff only returns fields that differ, which is right for finding
    changes but wrong for showing a chain: once an edit is put back, the value
    matches the original again and the field drops out of the diff. Its history
    is still worth showing, so the starting value is read directly.
    """
    if not fields:
        return {}
    with connection.cursor() as cur:
        # Columns DB167 never had (num_calves, depth_m, species_id...) have no
        # original to read. They are left out rather than asked for.
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'raw' AND table_name = %s""", [table])
        in_raw = {r[0] for r in cur.fetchall()}
        fields = [f for f in fields if f in in_raw]
        if not fields:
            return {}
        columns = ", ".join('"' + f.replace('"', '""') + '"::text' for f in fields)
        keys = {}
        for schema in ("raw", "dbo"):
            cur.execute("""
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = (%s || '.' || quote_ident(%s))::regclass AND i.indisprimary
            """, [schema, table])
            keys[schema] = cur.fetchone()[0]
        # pk is the record's Primary Key in dbo. Where that is the hashed id,
        # DB167's row is found by the Legacy ID the dbo record carries.
        legacy = str(pk)
        if keys["raw"] != keys["dbo"]:
            cur.execute(f'SELECT "{keys["raw"]}"::text FROM dbo."{table}" WHERE "{keys["dbo"]}"::text = %s',
                        [str(pk)])
            row = cur.fetchone()
            if row is None:
                return {}
            legacy = row[0]
        cur.execute(f'SELECT {columns} FROM raw."{table}" WHERE "{keys["raw"]}"::text = %s',
                    [legacy])
        row = cur.fetchone()
    return dict(zip(fields, row)) if row else {}


def _diff(table, pk):
    with connection.cursor() as cur:
        cur.execute("SELECT field, original, current FROM app.record_diff(%s, %s)",
                    [table, str(pk)])
        return OrderedDict((row[0], (row[1], row[2])) for row in cur.fetchall())


def record_history(view_name, pk):
    """
    Every field of one record whose value is not exactly what DB167 held, as a
    chain from the original through cleaning to the most recent edit.
    """
    table = DBO_TABLE.get(view_name)
    if not table:
        return [], []

    differences = _diff(table, pk)
    audit = _audit_rows(table, pk)
    rules = _rule_columns(table)

    # Fields that differ, plus any field an edit touched -- an edit that put a
    # value back to what DB167 said leaves no difference but is still history.
    fields = list(differences)
    edited_only = []
    for entry in audit:
        for field in entry["changes"]:
            if field not in fields:
                fields.append(field)
                edited_only.append(field)
    # Fields that match the original again -- an edit that was put back -- are
    # not in the diff, so their starting value is read from the frozen copy.
    originals = _raw_values(table, pk, edited_only)

    histories = []
    for field in fields:
        original, current = differences.get(field, (None, None))
        edits = [e for e in audit if field in e["changes"]]

        if field not in differences and edits:
            original = originals.get(field)
            current = _text(edits[-1]["changes"][field].get("new"))

        # Walk the edits backwards to find what cleaning left behind.
        after_cleaning = current
        for entry in reversed(edits):
            after_cleaning = _text(entry["changes"][field].get("old"))

        steps = [Step(original, "original")]

        if after_cleaning != original:
            claiming = rules.get(field, [])
            steps.append(Step(after_cleaning, "rule",
                              detail=" · ".join(claiming) or None))

        for entry in edits:
            steps.append(Step(
                _text(entry["changes"][field].get("new")), "edit",
                actor=entry["actor"], at=entry["at"], comment=entry["comment"],
                audit_id=entry["id"],
                restorable=entry["restored_by"] is None,
            ))

        if len(steps) > 1:
            histories.append(FieldHistory(field, steps, LABELS.get(field)))

    # Deletions and other whole-record actions have no field, so they are shown
    # apart from the per-field chains.
    # Named as the Audit Log names them, in Title Case.
    from datahealth.views import ACTION_LABELS
    record_actions = [dict(e, action_label=ACTION_LABELS.get(e["action"], e["action"].replace("_", " ").title()))
                      for e in audit if not e["changes"]]
    return histories, record_actions
