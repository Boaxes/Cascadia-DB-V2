"""TrackT — one GPS track file recorded during an effort."""

from . import Rule, SQL

TABLE = "TrackT"

RULES = [
    Rule(
        id="R8", table=TABLE, kind=SQL, columns=["Comments"],
        description="Track comments carry <br> tags and an auto-generated "
                    "statistics block. The tags are stripped, the text kept.",
        sql="""UPDATE dbo."TrackT"
               SET "Comments" = btrim(regexp_replace("Comments", '<[^>]*>', ' ', 'g'))
               WHERE "Comments" ~ '<[^>]*>'""",
    ),
]

CORRECTIONS = []

# The six tracks naming deleted vessel 41 were removed in Phase 2a, before the
# foreign keys were added, and are recorded in app.audit_log as deletions.
# V1 instead guessed the vessel from the file name (all six contain SK1, for
# SeaKeeper) -- the only value in V1 inferred from a file name rather than a
# data column. Not carried over.
