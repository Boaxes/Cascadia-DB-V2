"""
Cleaning rules, one file per source table.

A **rule** is a systematic change to many records that is not in dispute --
folding case-only spellings together, converting a unit, parsing a number out
of a text column. Rules are the reason `dbo` differs from `raw`.

A **correction** is a fix affecting a handful of records. Those are not rules.
They are applied once and written to `app.audit_log` under the actor
`legacy-cleanup`, carrying the original description as their comment, so they
read as what they are: someone's judgement about specific rows, not a policy.

The threshold is 20 records. Anything below it is a correction.

Things that are neither and appear in neither place: derived columns (`geom`,
`species_id`, effort positions, track statistics) compute values DB167 never
had, so there is no original to compare them against. Their provenance lives in
the data -- `start_coord_source` says per row where a position came from.
"""

NORMALIZE = "normalize"   # trim, then fold case-only variants to the commonest
MAP = "map"               # explicit from -> to on one column
SQL = "sql"               # anything that needs an expression


class Rule:
    """A systematic change. Applied to every row that matches, forever."""

    def __init__(self, id, description, table, columns=None, mapping=None,
                 kind=NORMALIZE, sql=None):
        self.id = id
        self.description = description
        self.table = table
        self.columns = columns or []
        self.mapping = mapping or {}
        self.kind = kind
        self.sql = sql


class Correction:
    """
    A fix to a few records. Applied once, then recorded in app.audit_log.

    `where` is the SQL that selects the affected rows, `set` what to write.
    Both are read back into the audit entry, so the log says exactly what
    happened rather than "some rows changed".

    Corrections are scoped to `"Research Group" = 'CRC'`. Every one of them
    comes from V1, and V1 only ever read CRC data -- its CSV exports were
    already filtered. So each is a judgement about CRC's records, not a general
    claim. `dbo` now holds every organisation's data, and applying CRC's
    vocabulary to theirs would destroy perfectly good records: DailyConditionT's
    quality codes look invalid on 1,418 rows against CRC's E/G/VG/F/P, but
    1,404 of those are other groups writing `Ex`/`Gd`/`Fr` or `Good`/`Fair`/
    `Poor` or a 1-5 scale. Scoped to CRC it is 14 rows, which is what V1 found.

    Set crc_only=False only for something genuinely universal.
    """

    def __init__(self, id, description, table, pk, set, where, expected=None,
                 crc_only=True):
        self.id = id
        self.description = description
        self.table = table
        self.pk = pk
        self.set = set
        self.where = where
        self.expected = expected
        self.crc_only = crc_only
