"""
The SQL Server script that puts the website's changes into DB167.

DB167 is the source of truth, and the website's Audit Log is the list of
everything the website has changed since DB167 was last imported. This turns
the whole log into T-SQL, in the order the changes were made, for somebody
who can write to DB167 to run.

Each record is found by its Legacy ID (DB167's own ID): the Primary Key for
most tables, and for the eight tables whose Primary Key on the website is a
hashed id (audit.LEGACY_ID), the Legacy ID the entry kept (legacy_pk). The
script is built so that it can be run again and changes nothing the second
time, and so that it never overwrites DB167's own work:

    update       writes the new value only where DB167 still holds the old one;
                 reports "Already Applied" if it already holds the new one,
                 else "Conflict, Skipped"
    create       adds the row with the website's own TrackID (DB167's TrackID
                 is an identity, so IDENTITY_INSERT keeps the number); a
                 TrackID held by a different file is a conflict
    delete       deletes the record and what depends on it, only if every row
                 still matches what the website kept of it
    restore      puts a kept record back, if none of its rows are there

Each entry is its own unit: it is written between a savepoint and a handler,
so a database error (a key already used, a table the website's copy did not
know) undoes that entry alone, reports it as "Error, Skipped" with the error
and carries on, and everything that worked is committed. An entry that follows
a create that was skipped is skipped too.

An upload or a file edit writes nothing: DB167 holds only the names of the
track files, not the files. The fields the website works out itself
(daily_effort_id, track_status, a track's line) have no column in DB167 and
are left out. Any action not known here is reported as not applicable.

The website holds text as the build cleans it (spaces trimmed, capitals
merged, empty made NULL), so an old value, and the rows a delete checks, are
compared ignoring capitals and surrounding spaces. A new value is compared
exactly: that is what the script would write.

A track's StartTime and EndTime are written, and compared, as Pacific local time,
which is what DB167 holds. The log keeps them in UTC, like the track files, and
they are converted when it is read (_track_times_as_db167_holds), with daylight
saving. In the repeated hour of the autumn clock change two UTC moments an hour apart
(08:30 and 09:30) are both 01:30 Pacific, so DB167 cannot tell them apart; the build
reads such a time back by the file's own first or last time (macros/track_times.sql).

A track is matched to an Effort by the Effort's hashed id, which holds when DB167
renumbers the Effort, while the EffortID an entry kept is the number the Effort had
then. The script writes, and compares with, the Effort's number now (found by the hashed
id, in effort_numbers), and uses the entry's own number only if the Effort cannot be
found, so a track is not given back an Effort number DB167 has since changed.

Nothing in here touches a database except reading: generate() reads the log
and DB167's columns from Postgres, and write() takes both as arguments so it
can be tested alone.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from . import audit

# Postgres types (as raw holds DB167's) by how they are written in T-SQL.
INTEGERS = {"integer", "smallint", "bigint"}
FLOATS = {"double precision", "real"}
BINARY = "bytea"        # SightingT's computed hash columns: never written or compared

# The fields the website works out from a DB167 column or its track file, so
# changing one is no change DB167 is missing (daily_effort_id follows EffortID).
MIRRORS = {"daily_effort_id", "track_status", "geom", "length_nm", "point_count", "file_name", "vessel_id"}

# What names the same track when a TrackID is taken: the file it holds.
SAME_ROW_BY = {"TrackT": "TrackFileName"}

BIN = "COLLATE Latin1_General_100_BIN2"
CI = "COLLATE Latin1_General_100_CI_AS"


class Schema:
    """DB167's tables as raw holds them: {table: {column: Postgres type}} in
    DB167's column order, and each table's Primary Key column."""

    def __init__(self, columns, keys):
        self.columns = columns
        self.keys = keys

    @classmethod
    def read(cls, cursor):
        cursor.execute("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relnamespace = 'raw'::regnamespace AND c.relkind = 'r'
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY c.relname, a.attnum
        """)
        columns = {}
        for table, column, kind in cursor.fetchall():
            columns.setdefault(table, {})[column] = kind
        cursor.execute("""
            SELECT c.relname, a.attname
            FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE c.relnamespace = 'raw'::regnamespace AND i.indisprimary
        """)
        return cls(columns, dict(cursor.fetchall()))

    def writable(self, table):
        """The columns the script may write or compare, in order."""
        return {c: t for c, t in self.columns.get(table, {}).items() if t != BINARY}


def read_entries(cursor):
    """The whole Audit Log, oldest first."""
    cursor.execute("""
        SELECT id, occurred_at, actor_name, action, target_table, target_pk, legacy_pk,
               changes, snapshot, comment, restored_by
        FROM app.audit_log ORDER BY id
    """)
    names = ("id", "at", "actor", "action", "table", "pk", "legacy_pk",
             "changes", "snapshot", "comment", "restored_by")
    entries = []
    for row in cursor.fetchall():
        entry = dict(zip(names, row))
        entry["changes"] = audit._json(entry["changes"])
        entry["snapshot"] = audit._json(entry["snapshot"])
        _track_times_as_db167_holds(entry)
        entries.append(entry)
    numbers = effort_numbers(cursor, entries)
    for entry in entries:
        _efforts_as_db167_holds(entry, numbers)
    return entries


def effort_numbers(cursor, entries):
    """{hashed Effort id: the Effort's Legacy ID now}, for every Effort a TrackT entry names
    by its hashed id (daily_effort_id), in what it changes and in the rows it kept."""
    ids = set()
    for entry in entries:
        if entry["table"] != "TrackT":
            continue
        change = (entry["changes"] or {}).get("daily_effort_id")
        for side in (change.values() if isinstance(change, dict) else ()):
            if side is not None:
                ids.add(int(side))
        for row in ((entry["snapshot"] or {}).get("TrackT") or []):
            if row.get("daily_effort_id") is not None:
                ids.add(int(row["daily_effort_id"]))
    if not ids:
        return {}
    cursor.execute('SELECT id, "DailyEffortID" FROM dbo."DailyEffortT" WHERE id = ANY(%s)', [sorted(ids)])
    return dict(cursor.fetchall())


def _efforts_as_db167_holds(entry, numbers):
    """A track is matched to an Effort by the Effort's hashed id, which holds when DB167
    renumbers it; the EffortID an entry kept is the number it had at the time, which may
    be out of date. DB167 is written, and compared with, the Effort's number now. The old
    number is used only where the Effort cannot be found."""
    if entry["table"] != "TrackT":
        return
    change = (entry["changes"] or {}).get("daily_effort_id")
    typed = (entry["changes"] or {}).get("EffortID")
    if isinstance(change, dict) and isinstance(typed, dict):
        for side in ("old", "new"):
            if change.get(side) is not None and int(change[side]) in numbers:
                typed[side] = numbers[int(change[side])]
    for row in ((entry["snapshot"] or {}).get("TrackT") or []):
        if row.get("daily_effort_id") is not None and int(row["daily_effort_id"]) in numbers:
            row["EffortID"] = numbers[int(row["daily_effort_id"])]


# A track's StartTime and EndTime are the one place the website's value and
# DB167's differ in kind: the website keeps them in UTC, like the track files,
# and DB167 in Pacific local time. The script writes, and compares with, what
# DB167 holds, so these are converted when the log is read. The log itself stays
# in UTC.
PACIFIC = ZoneInfo("America/Los_Angeles")
TRACK_TIMES = ("StartTime", "EndTime")


def pacific_from_utc(value):
    """2026-08-26 16:21:51 (UTC) as 2026-08-26 09:21:51 (Pacific local time, with
    daylight saving), keeping any fraction of a second."""
    at = datetime.fromisoformat(str(value).replace("T", " ")).replace(tzinfo=timezone.utc)
    local = at.astimezone(PACIFIC)
    return local.strftime("%Y-%m-%d %H:%M:%S") + (f".{local.microsecond // 1000:03d}" if local.microsecond else "")


def _track_times_as_db167_holds(entry):
    """Give a TrackT entry's StartTime and EndTime, in its changes (old and
    new) and in the rows its snapshot kept, as Pacific local time."""
    if entry["table"] != "TrackT":
        return
    for column in TRACK_TIMES:
        change = (entry["changes"] or {}).get(column)
        if isinstance(change, dict):
            for side in ("old", "new"):
                if change.get(side):
                    change[side] = pacific_from_utc(change[side])
    for row in ((entry["snapshot"] or {}).get("TrackT") or []):
        for column in TRACK_TIMES:
            if row.get(column):
                row[column] = pacific_from_utc(row[column])


# ---------------------------------------------------------------------------
# Writing values
# ---------------------------------------------------------------------------


def ident(name):
    """A table or column name, in brackets."""
    return "[" + name.replace("]", "]]") + "]"


def text(value):
    return "N'" + str(value).replace("'", "''") + "'"


def literal(value, kind):
    """A value as a T-SQL literal for a column of Postgres type `kind`."""
    if value is None:
        return "NULL"
    if kind in INTEGERS:
        if isinstance(value, bool):
            return "1" if value else "0"
        try:
            number = Decimal(str(value))
            if number != number.to_integral_value():
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError(f"{value!r} is not a whole number")
        return str(int(number))
    if kind in FLOATS:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{value!r} is not a number")
        written = repr(number)
        return written.upper() if "e" in written else written + "E0"
    if kind.startswith("numeric"):
        try:
            return format(Decimal(str(value)), "f")
        except InvalidOperation:
            raise ValueError(f"{value!r} is not a number")
    if kind == "boolean":
        if isinstance(value, str):
            value = value.strip().lower() in ("true", "t", "1", "yes")
        return "1" if value else "0"
    if kind == "date":
        found = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value))
        if not found:
            raise ValueError(f"{value!r} is not a date")
        return "'" + found.group(1) + "'"
    if kind.startswith("timestamp"):
        return "'" + _moment(value) + "'"
    if kind.startswith("time"):
        found = re.match(r"^(\d{1,2}:\d{2}:\d{2})(\.\d+)?", str(value))
        if not found:
            raise ValueError(f"{value!r} is not a time")
        return "'" + found.group(1) + (found.group(2) or "")[:4] + "'"
    return text(value)


def _moment(value):
    """A date and time as ISO 8601 with a T, which SQL Server reads the same
    in every language, to the 3 decimals a datetime holds."""
    found = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}:\d{2}(?::\d{2})?)(\.\d+)?)?", str(value))
    if not found:
        raise ValueError(f"{value!r} is not a date and time")
    clock = found.group(2) or "00:00:00"
    if clock.count(":") == 1:
        clock += ":00"
    datetime.strptime(found.group(1) + " " + clock, "%Y-%m-%d %H:%M:%S")      # a real moment
    return f"{found.group(1)}T{clock}{(found.group(3) or '')[:4]}"


def holds(column, kind, value):
    """A condition: the column holds exactly this value. Always true or false,
    never unknown, so it can be negated."""
    c = ident(column)
    if value is None:
        return f"{c} IS NULL"
    if kind == "text":
        return f"({c} IS NOT NULL AND CAST({c} AS nvarchar(max)) {BIN} = {literal(value, kind)})"
    return f"({c} IS NOT NULL AND {c} = {literal(value, kind)})"


def held(column, kind, value):
    """The same, for what the website kept of a value DB167 holds: text
    ignoring capitals and surrounding spaces, empty the same as NULL."""
    if kind != "text":
        return holds(column, kind, value)
    c = ident(column)
    trimmed = f"NULLIF(LTRIM(RTRIM(CAST({c} AS nvarchar(max)))), N'')"
    if value is None or str(value).strip() == "":
        return f"{trimmed} IS NULL"
    return f"({trimmed} IS NOT NULL AND {trimmed} {CI} = {literal(value, kind)})"


def any_of(conditions):
    return conditions[0] if len(conditions) == 1 else "(" + " OR ".join(conditions) + ")"


def identity(table_name, state):
    """SET IDENTITY_INSERT, for a table that has an identity column in DB167
    (SQL Server refuses it, Msg 8106, on one that has none). Read from DB167
    when the script runs, because raw does not keep it."""
    return (f"IF OBJECTPROPERTY(OBJECT_ID({text(table_name)}), 'TableHasIdentity') = 1 "
            f"SET IDENTITY_INSERT {table_name} {state};")


def one_line(value, limit=140):
    """Text for a comment or the report: one line, nothing that could end it."""
    flat = re.sub(r"\s+", " ", str(value or "")).strip().replace("*/", "* /")
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------


class Writer:
    """One run of the script: the entries and DB167's columns, written out."""

    def __init__(self, entries, schema):
        self.schema = schema
        self.lines = []
        self.writes = False         # whether the entry being written changes DB167
        self.identity = []          # tables it turns IDENTITY_INSERT on for
        self.made = set()           # (table, key) of the records created so far in the script
        # Entries that cancel out: one the old Restore put back, and the
        # restore itself.
        self.cancelled = {e["id"] for e in entries if e["restored_by"]} | \
                         {e["restored_by"] for e in entries if e["restored_by"]}
        # What later entries set a field to, so a field changed twice is
        # still "Already Applied" once both have been written.
        self.later = {}
        # The changes made to one field (id, old, new), and every entry about one
        # record (id, action).
        self.chain, self.timeline = {}, {}
        for e in entries:
            if e["id"] in self.cancelled:
                continue
            record = self.record(e)
            self.timeline.setdefault((e["table"], str(record)), []).append((e["id"], e["action"]))
            for column, change in (e["changes"] or {}).items():
                new = change.get("new") if isinstance(change, dict) else None
                self.later.setdefault((e["table"], record, column), []).append((e["id"], new))
                if e["action"] in ("update", "associate", "dissociate", "restore") and not e["snapshot"] \
                        and isinstance(change, dict):
                    self.chain.setdefault((e["table"], record, column), []).append(
                        (e["id"], change.get("old"), new))
        # A change to a field is Superseded when the very next entry about the
        # record changes the same field again: it is not written only to be
        # written over. Anything else in between (a delete, a restore, another
        # field) and it is written as it stands. `absorbed` holds what the
        # last change of such a run starts from: the old and new value of each
        # change before it.
        self.overridden, self.absorbed = {}, {}
        for (table, record, column), changes in self.chain.items():
            events = [i for i, _ in self.timeline.get((table, str(record)), [])]
            for (a, a_old, a_new), (b, _, _) in zip(changes, changes[1:]):
                if events.index(b) == events.index(a) + 1:
                    self.overridden[(a, column)] = b
                    self.absorbed[(b, column)] = self.absorbed.get((a, column), []) + [a_old, a_new]

    # -- addressing --------------------------------------------------------

    def key_column(self, table):
        return audit.LEGACY_ID.get(table) or self.schema.keys.get(table)

    def record(self, entry):
        """The Legacy ID of the record an entry is about, or None."""
        table = entry["table"]
        if table in audit.LEGACY_ID:
            kept = (entry["snapshot"] or {}).get(table)
            if entry["legacy_pk"] is None and entry["action"] == "delete" and isinstance(kept, list) and kept:
                return kept[0].get(audit.LEGACY_ID[table])
            return entry["legacy_pk"]
        return entry["pk"]

    def where(self, table, value):
        key = self.key_column(table)
        return f"{ident(key)} = {literal(value, self.schema.columns[table][key])}"

    # -- output ------------------------------------------------------------

    def add(self, *lines):
        self.lines.extend(lines)

    def report(self, entry_id, result, detail, indent=""):
        return (f"{indent}INSERT INTO #Report (EntryID, Result, Detail) "
                f"VALUES ({entry_id}, {text(result)}, {text(one_line(detail, 300))});")

    def heading(self, entry, what):
        when = entry["at"].strftime("%Y-%m-%d %H:%M") if entry["at"] else ""
        note = f" Note: {one_line(entry['comment'], 100)}" if entry["comment"] else ""
        self.add("", f"-- Entry {entry['id']}, {when}, {one_line(entry['actor'], 60)}: {one_line(what, 80)}.{note}")

    # -- one entry ---------------------------------------------------------

    def entry(self, entry):
        table, action, number = entry["table"], entry["action"], entry["id"]
        record = self.record(entry)
        what = f"{action} {table} {record if record is not None else entry['pk']}"
        self.heading(entry, what)
        self.writes, self.identity = False, []
        mark = len(self.lines)

        def skip(result, why):
            self.add(self.report(number, result, f"{what}: {why}"))

        try:
            if number in self.cancelled:
                skip("Not Applicable", "put back through the old Restore, so it cancels out")
            elif action in ("upload", "edit_file"):
                skip("Not Applicable", "DB167 holds only the names of track files, so there is nothing to write")
            elif table not in self.schema.columns or table not in self.schema.keys:
                skip("Not Applicable", f"{table} is not a DB167 table")
            elif action == "create":
                self.create(entry, what)
            elif action == "delete":
                self.delete(entry, what)
            elif action == "restore" and entry["snapshot"]:
                self.restore(entry, what)
            elif action in ("update", "associate", "dissociate", "restore"):
                self.update(entry, what)
            else:
                skip("Not Applicable", f"the {action} kind of change is not written to DB167")
        except ValueError as error:
            del self.lines[mark:]
            self.writes = False
            self.add(self.report(number, "Conflict, Skipped", f"{what}: could not be written ({error})"))
        if not self.writes:
            return
        body = self.lines[mark:]
        del self.lines[mark:]
        self.unit(entry, what, body)

    def unit(self, entry, what, body):
        """An entry that writes, as a unit of its own: a savepoint, and a
        handler that undoes just this entry if anything fails."""
        table, number = entry["table"], entry["id"]
        key = entry["pk"]
        if entry["action"] != "create" and (table, str(key)) in self.made:
            # The create this one follows may have been skipped.
            body = [f"IF EXISTS (SELECT 1 FROM #Skipped WHERE TableName = {text(table)} AND RecordID = {text(key)})",
                    "    " + self.report(number, "Skipped, Its Create Conflicted", what),
                    "ELSE", "BEGIN"] + ["    " + line for line in body] + ["END"]
        if entry["action"] == "create":
            self.made.add((table, str(key)))
        handler = [f"    {identity(t, 'OFF')}" for t in self.identity]
        message = f"{one_line(what, 200)}: error "
        self.add("BEGIN TRY", "    SAVE TRANSACTION Entry;")
        self.add(*["    " + line for line in body])
        self.add("END TRY", "BEGIN CATCH",
                 "    SET @ErrorNumber = ERROR_NUMBER(); SET @ErrorMessage = ERROR_MESSAGE();",
                 *handler,
                 # A transaction SQL Server has given up on cannot be rolled back to a savepoint.
                 f"    IF XACT_STATE() <> 1 BEGIN SET @FailedEntry = {number}; SET @FailedWhat = {text(one_line(what, 200))}; GOTO Doomed; END",
                 "    ROLLBACK TRANSACTION Entry;",
                 f"    INSERT INTO #Report (EntryID, Result, Detail) VALUES ({number}, N'Error, Skipped', "
                 f"LEFT({text(message)} + CAST(@ErrorNumber AS nvarchar(20)) + N', ' + @ErrorMessage, 400));")
        if entry["action"] == "create":
            self.add(f"    INSERT INTO #Skipped (TableName, RecordID) VALUES ({text(table)}, {text(key)});")
        self.add("END CATCH;")

    def update(self, entry, what):
        table, number = entry["table"], entry["id"]
        record = self.record(entry)
        columns = self.schema.writable(table)
        key = self.key_column(table)
        fields = [(c, ch) for c, ch in (entry["changes"] or {}).items()
                  if c in columns and c != key and isinstance(ch, dict)]
        if not fields:
            self.add(self.report(number, "Not Applicable",
                                 f"{what}: only fields the website works out itself changed"))
            return
        if record is None:
            self.add(self.report(number, "Conflict, Skipped", f"{what}: the entry has no Legacy ID to find the record by"))
            return
        worked_out = [c for c in (entry["changes"] or {}) if c not in columns and c not in MIRRORS]
        if worked_out:
            self.add(self.report(number, "Not Applicable",
                                 f"{table} {record}, {', '.join(worked_out)}: worked out by the website, not DB167 columns"))
        for column, change in fields:
            kind = columns[column]
            old, new = change.get("old"), change.get("new")
            detail = f"{table} {record}, {column}"
            after = self.overridden.get((number, column))
            if after:
                self.add(self.report(number, "Superseded", f"{detail}: NOT WRITTEN, because entry {after} changes it "
                                     f"again straight after. If entry {after} is skipped, this one is not applied either"))
                continue
            # The last change of a run starts from where the first one did, or
            # from any value the ones it overrides would have left it at.
            olds = []
            for v in self.absorbed.get((number, column), []) + [old]:
                if v not in olds:
                    olds.append(v)
            self.writes = True
            again = [v for i, v in self.later.get((table, self.record(entry), column), []) if i > number]
            applied = any_of([holds(column, kind, v) for v in [new] + again])
            where = self.where(table, record)
            self.add(
                f"UPDATE {ident('dbo')}.{ident(table)} SET {ident(column)} = {literal(new, kind)}",
                f"WHERE {where} AND {any_of([held(column, kind, o) for o in olds])} AND NOT {holds(column, kind, new)};",
                f"IF @@ROWCOUNT = 1 {self.report(number, 'Applied', detail)}",
                f"ELSE IF EXISTS (SELECT 1 FROM {ident('dbo')}.{ident(table)} WHERE {where} AND {applied})",
                f"    {self.report(number, 'Already Applied', detail)}",
                "ELSE",
                f"    {self.report(number, 'Conflict, Skipped', detail + ': DB167 holds neither the old value nor the new one, or has no such record')}")

    def create(self, entry, what):
        table, number = entry["table"], entry["id"]
        if table in audit.LEGACY_ID:
            self.add(self.report(number, "Not Applicable",
                                 f"{what}: DB167 numbers {table} records itself, so this one has no Legacy ID to keep"))
            return
        columns = self.schema.writable(table)
        key = self.key_column(table)
        values = {c: ch.get("new") for c, ch in (entry["changes"] or {}).items()
                  if c in columns and isinstance(ch, dict)}
        values[key] = entry["pk"]
        names = [c for c in columns if c in values]
        same = SAME_ROW_BY.get(table)
        where = self.where(table, entry["pk"])
        detail = f"{table} {entry['pk']}"
        table_name = f"{ident('dbo')}.{ident(table)}"
        self.writes, self.identity = True, [table_name]
        self.add(
            f"IF NOT EXISTS (SELECT 1 FROM {table_name} WHERE {where})",
            "BEGIN",
            f"    {identity(table_name, 'ON')}",
            f"    INSERT INTO {table_name} ({', '.join(ident(c) for c in names)})",
            f"    VALUES ({', '.join(literal(values[c], columns[c]) for c in names)});",
            f"    {identity(table_name, 'OFF')}",
            self.report(number, "Applied", detail, "    "),
            "END")
        if same and same in values:
            self.add(
                f"ELSE IF EXISTS (SELECT 1 FROM {table_name} WHERE {where} AND {holds(same, columns[same], values[same])})",
                f"    {self.report(number, 'Already Applied', detail)}",
                "ELSE",
                "BEGIN",
                f"    {self.report(number, 'Conflict, Skipped', detail + ': DB167 already uses this ' + key + ' for a different ' + same)}",
                f"    INSERT INTO #Skipped (TableName, RecordID) VALUES ({text(table)}, {text(str(entry['pk']))});",
                "END")
        else:
            self.add("ELSE", f"    {self.report(number, 'Already Applied', detail)}")

    def rows(self, entry, children_first):
        """(table, row) for every row the entry's snapshot kept: the record
        first and what depends on it after, or the other way round."""
        snapshot = entry["snapshot"] or {}
        table = entry["table"]
        below = [t for t in snapshot.get("__order__", []) if t != table]
        for t in snapshot:
            if t not in below and t != table and t != "__order__" and isinstance(snapshot[t], list):
                below.append(t)
        order = list(reversed(below)) + [table] if children_first else [table] + below
        return [(t, row) for t in order for row in snapshot.get(t, []) if isinstance(row, dict)]

    def delete(self, entry, what):
        number = entry["id"]
        if not isinstance(entry["snapshot"], dict) or not entry["snapshot"].get(entry["table"]):
            self.add(self.report(number, "Conflict, Skipped", f"{what}: the entry kept no copy of the record"))
            return
        found = []
        for table, row in self.rows(entry, children_first=True):
            columns = self.schema.writable(table)
            key = self.key_column(table)
            if table not in self.schema.columns or key is None or row.get(key) is None:
                continue
            where = self.where(table, row[key])
            guard = " AND ".join(held(c, columns[c], row[c]) for c in columns if c in row and c != key)
            found.append((f"{ident('dbo')}.{ident(table)}", where, guard))
        if not found:
            self.add(self.report(number, "Conflict, Skipped", f"{what}: the entry kept no row DB167 has a table for"))
            return
        below = ", ".join(f"{t} {len(rows)}" for t, rows in entry["snapshot"].items()
                          if isinstance(rows, list) and t not in (entry["table"], "__order__") and rows)
        detail = f"{what} (with {below})" if below else what
        any_there = " OR ".join(f"EXISTS (SELECT 1 FROM {t} WHERE {w})" for t, w, g in found)
        changed = " OR ".join(f"EXISTS (SELECT 1 FROM {t} WHERE {w}{' AND NOT (' + g + ')' if g else ''})"
                              for t, w, g in found)
        self.writes = True
        self.add(f"IF NOT ({any_there})", f"    {self.report(number, 'Already Applied', detail)}",
                 f"ELSE IF {changed}",
                 f"    {self.report(number, 'Conflict, Skipped', detail + ': a row is no longer as the website kept it')}",
                 "ELSE", "BEGIN")
        for t, w, g in found:
            self.add(f"    DELETE FROM {t} WHERE {w}{' AND ' + g if g else ''};")
        self.add(self.report(number, "Applied", detail, "    "), "END")

    def restore(self, entry, what):
        number = entry["id"]
        found = []
        for table, row in self.rows(entry, children_first=False):
            columns = self.schema.writable(table)
            key = self.key_column(table)
            if table not in self.schema.columns or key is None or row.get(key) is None:
                continue
            names = [c for c in columns if c in row]
            found.append((f"{ident('dbo')}.{ident(table)}", self.where(table, row[key]), names,
                          [literal(row[c], columns[c]) for c in names]))
        if not found:
            self.add(self.report(number, "Conflict, Skipped", f"{what}: the entry kept no row DB167 has a table for"))
            return
        self.writes, self.identity = True, [t for t, w, n, v in found]
        every = " AND ".join(f"EXISTS (SELECT 1 FROM {t} WHERE {w})" for t, w, n, v in found)
        none = " AND ".join(f"NOT EXISTS (SELECT 1 FROM {t} WHERE {w})" for t, w, n, v in found)
        self.add(f"IF {none}", "BEGIN")
        for t, w, names, values in found:
            self.add(f"    {identity(t, 'ON')}",
                     f"    INSERT INTO {t} ({', '.join(ident(c) for c in names)})",
                     f"    VALUES ({', '.join(values)});",
                     f"    {identity(t, 'OFF')}")
        self.add(self.report(number, "Applied", what, "    "), "END",
                 f"ELSE IF {every}", f"    {self.report(number, 'Already Applied', what)}",
                 "ELSE", f"    {self.report(number, 'Conflict, Skipped', what + ': only some of its rows are in DB167')}")


def write(entries, schema, generated=None):
    """The whole script, as text."""
    writer = Writer(entries, schema)
    stamp = (generated or datetime.now()).strftime("%Y-%m-%d %H:%M")
    span = f"entries {entries[0]['id']} to {entries[-1]['id']}" if entries else "no entries"
    head = [
        "-- Cascadia Website Changes For DB167",
        f"-- Written {stamp} from the website's Audit Log: {len(entries)} entries, {span}.",
        "--",
        "-- What this does: makes every change made on the website in DB167, in the order",
        "-- it was made. Each change is checked first.",
        "--   Applied            DB167 had the old value, and now has the new one.",
        "--   Already Applied    DB167 already had the change. Nothing was written.",
        "--   Conflict, Skipped  DB167 holds something else. Nothing was written. Nothing is",
        "--                      ever forced; look at it by hand.",
        "--   Not Applicable     Nothing DB167 holds: a track file upload or edit, or a field",
        "--                      the website works out itself.",
        "--   Superseded         NOT WRITTEN: the very next entry about the same record changes",
        "--                      the same field again, so only the last change is written. If",
        "--                      that later change is skipped (a conflict, or an error), this",
        "--                      earlier one is not applied either.",
        "--   Error, Skipped     SQL Server refused the change (the error is in the report).",
        "--                      That entry alone is undone.",
        "--   Skipped, Its Create Conflicted   The track it is about was not added, so it is skipped.",
        "--",
        "-- Each entry is its own unit inside one transaction, and what worked is committed",
        "-- at the end with a report of every entry. It can be run again: the second time",
        "-- changes nothing. Run it on a copy of DB167 first, and take a backup before",
        "-- running it on DB167 itself.",
        "--",
        "-- One thing can still stop it: an error that makes SQL Server give up on the whole",
        "-- transaction, which cannot be undone entry by entry. Then everything is rolled",
        "-- back, the report up to that entry is printed with a message naming the entry",
        "-- and the error, and the script stops. NOTHING IS COMMITTED in that case, not even",
        "-- the entries before it.",
        "",
        # The settings DB167's computed and indexed columns need to be written,
        # which SQL Server Management Studio has on and sqlcmd does not.
        "SET ANSI_NULLS ON; SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; SET ARITHABORT ON;",
        "SET CONCAT_NULL_YIELDS_NULL ON; SET QUOTED_IDENTIFIER ON; SET NUMERIC_ROUNDABORT OFF;",
        "SET NOCOUNT ON;",
        "SET DATEFORMAT ymd;",
        # Off, so that an error inside an entry leaves the transaction usable and
        # the entry can be undone to its savepoint (with it on, the whole
        # transaction would be lost).
        "SET XACT_ABORT OFF;",
        "DECLARE @ErrorNumber int, @ErrorMessage nvarchar(2000), @FailedEntry int, @FailedWhat nvarchar(300);",
        # A table variable, because a rolled back transaction takes #Report with it.
        "DECLARE @Saved TABLE (Seq int IDENTITY(1, 1), EntryID int, Result nvarchar(40), Detail nvarchar(400));",
        "",
        "CREATE TABLE #Report (",
        "    Seq      int IDENTITY(1, 1) PRIMARY KEY,",
        "    EntryID  int NOT NULL,",
        "    Result   nvarchar(40) NOT NULL,",
        "    Detail   nvarchar(400) NOT NULL",
        ");",
        "-- Tracks the script did not add, so what follows them is skipped.",
        "CREATE TABLE #Skipped (TableName nvarchar(128) NOT NULL, RecordID nvarchar(50) NOT NULL);",
        "",
        "BEGIN TRAN;",
    ]
    for entry in entries:
        writer.entry(entry)
    tail = [
        "",
        "-- The report",
        "SELECT EntryID AS [Entry], Result AS [Result], Detail AS [Detail] FROM #Report ORDER BY Seq;",
        "SELECT Result AS [Result], COUNT(*) AS [Entries] FROM #Report GROUP BY Result ORDER BY Result;",
        "",
        "IF XACT_STATE() = 1 COMMIT;",
        "RETURN;",
        "",
        "-- SQL Server gave up on the transaction: nothing can be committed.",
        "Doomed:",
        "INSERT INTO @Saved (EntryID, Result, Detail) SELECT EntryID, Result, Detail FROM #Report "
        "WHERE EntryID <> @FailedEntry ORDER BY Seq;",
        "IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;",
        "SELECT N'Every entry below was rolled back. Nothing was committed. The list can be empty.' AS [Report Up To The Failure];",
        "SELECT EntryID AS [Entry], Result AS [Result], Detail AS [Detail] FROM @Saved ORDER BY Seq;",
        "DECLARE @Why nvarchar(2000) = LEFT(N'Entry ' + CAST(@FailedEntry AS nvarchar(20)) + N' (' + @FailedWhat "
        "+ N') made SQL Server give up on the transaction: error ' + CAST(@ErrorNumber AS nvarchar(20)) + N', ' "
        "+ @ErrorMessage + NCHAR(10) + N'NOTHING WAS COMMITTED. Every entry the script had written was rolled back, whether or not it is "
        "listed above (the list can be empty, because a rollback inside a trigger also removes the report). "
        "Fix what that entry ran into, or take it out of the log, and run the script again.', 2000);",
        "RAISERROR(N'%s', 16, 1, @Why);",
        "RETURN;",
        "",
    ]
    return "\n".join(head + writer.lines + tail)


def generate(cursor):
    """The script for the log as it is now."""
    return write(read_entries(cursor), Schema.read(cursor))


def filename(now=None):
    return f"Cascadia-DB167-Migration-{(now or datetime.now()).strftime('%Y-%m-%d-%H%M')}.sql"
