"""
A fingerprint of every table and view a build made, to prove a build is
deterministic: two builds from the same inputs must give the same fingerprints.

    python verify/checksums.py --db test_today --schemas build_next,dbo_next,app_next --out first.json
    python verify/checksums.py --compare first.json second.json

Each relation's fingerprint is its row count and the MD5 of its rows' MD5s,
sorted, so it does not depend on the order Postgres returns rows in.
"""

import argparse
import json
import sys

import psycopg

URL = "postgresql://cascadia:cascadia@db:5432/{}"


def fingerprints(db, schemas):
    out = {}
    with psycopg.connect(URL.format(db)) as conn, conn.cursor() as cur:
        cur.execute("""select n.nspname, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
                       where n.nspname = any(%s) and c.relkind in ('r', 'v') order by 1, 2""", [schemas])
        for schema, name in cur.fetchall():
            cur.execute(f'select count(*), md5(coalesce(string_agg(h, \'\' order by h), \'\')) '
                        f'from (select md5(t::text) as h from "{schema}"."{name}" t) x')
            count, digest = cur.fetchone()
            # The schema's own name is left out, so dbo_next and dbo compare.
            out[f"{schema.removesuffix('_next')}.{name}"] = [count, digest]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db")
    parser.add_argument("--schemas", default="build_next,dbo_next,app_next")
    parser.add_argument("--out")
    parser.add_argument("--compare", nargs=2)
    args = parser.parse_args()
    if args.compare:
        a, b = (json.load(open(p)) for p in args.compare)
        differ = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        print(f"{len(a)} relations compared; {len(differ)} differ")
        for k in differ:
            print(f"  {k}: {a.get(k)} vs {b.get(k)}")
        return 1 if differ else 0
    result = fingerprints(args.db, args.schemas.split(","))
    json.dump(result, open(args.out, "w"), indent=1, sort_keys=True)
    print(f"{len(result)} relations, {sum(c for c, _ in result.values()):,} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
