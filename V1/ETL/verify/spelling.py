"""
The spelling rule (rule 5), worked out again in Python from the seeds and
DB167's own values, without reading anything the build made. The checks use it
to know what dbo should hold, so they never take the build's word for it.

It follows models/build/spelling_map.sql step for step:

  1. Every value of every choice column (seeds/column_kinds.csv), grouped by
     its unit: the column, or the vocabulary it shares with other columns.
  2. Sub-area values in Doug Sandilands's table (seeds/sub_areas.csv) become
     his corrected sub-area.
  3. Other values are grouped by their key (trimmed, spaces made one, lower
     case), and groups are joined by the typo and synonym lists.
  4. Each joined set becomes one spelling: the category table's, or else the
     one nearest Title Case (fewest capitals for a unit of measure), then the
     most common, then the first in character order.

    merges(cur)  ->  {(table, column, value): (spelling, kind)}
"""

import collections
import csv
import pathlib
import re

SEEDS = pathlib.Path(__file__).resolve().parent.parent / "dbt" / "seeds"

# What Postgres trims (btrim with this set) and what its \s matches. Python's
# own \s also matches a non-breaking space inside text, which Postgres's does not.
TRIM = " \t\r\n\f\v "
SPACES = re.compile("[\t\n\v\f\r   -  -    　]+")
MINOR = {"a", "an", "and", "at", "by", "de", "del", "for", "from", "in", "la", "of", "on", "or", "the", "to",
         "van", "von", "with"}


def seed(name):
    with open(SEEDS / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normal(value):
    """Trimmed, runs of spaces made one."""
    return SPACES.sub(" ", value.strip(TRIM))


def key_text(value):
    """As build.key_text: normal, in lower case; empty text is None."""
    if value is None:
        return None
    return normal(str(value)).lower() or None


def spelling_key(unit, value):
    k = key_text(value)
    if unit == "SightingT.Group Type" and k is not None:
        k = re.sub(r"\s*\+\s*", "+", k)
        k = re.sub(r"(?<=\w)\s*x\s*(?=\d)", "x", k)
    return k


def title_distance(s):
    """How many letters a spelling is from Title Case, as build.title_distance."""
    total = 0
    for pos, word in enumerate(re.findall(r"[A-Za-z']+", s), start=1):
        if re.fullmatch(r"(Mc|Mac|O')[A-Z][a-z]+", word):
            continue
        if re.fullmatch(r"Mc[a-z]+", word):
            total += 1
            continue
        letters = re.sub(r"[^A-Za-z]", "", word)
        title = sum(1 for j, ch in enumerate(letters) if ("A" <= ch <= "Z") != (j == 0))
        caps = sum(1 for ch in letters if not "A" <= ch <= "Z") if len(letters) <= 4 else title
        low = sum(1 for ch in letters if "A" <= ch <= "Z") if pos > 1 and word.lower() in MINOR else title
        total += min(title, caps, low)
    return total


def unit_distance(s):
    return sum(1 for ch in s if ch.isupper())


def choice_columns():
    """{(table, column): unit} for every choice column."""
    return {(r["table_name"], r["column_name"]): r["vocabulary"] or f'{r["table_name"]}.{r["column_name"]}'
            for r in seed("column_kinds") if r["kind"] == "choice"}


def raw_values(cur, columns):
    """{unit: {value: records}}, as DB167 has them, empty text left out."""
    out = collections.defaultdict(collections.Counter)
    for (table, column), unit in sorted(columns.items()):
        cur.execute(f'select "{column}"::text, count(*) from raw."{table}" where "{column}" is not null group by 1')
        for value, n in cur.fetchall():
            if value.strip(TRIM):
                out[unit][value] += n
    return out


def categories(cur):
    """The category tables' spellings, by unit."""
    out = collections.defaultdict(list)
    for unit, sql in [("species", 'select "Abbreviation" from raw."SpeciesT"'),
                      ("research_group", 'select "Code" from raw."ResearchGroupT"'),
                      ("vessel", 'select "VesselCode" from raw."VesselT"'),
                      ("DailyEventT.Code", 'select "EventCode" from raw."EventCodeT"')]:
        cur.execute(sql)
        out[unit] += [r[0] for r in cur.fetchall() if r[0] is not None]
    out["species"] += [r["code"] for r in seed("species_added")]
    return out


def unit_merges(unit, values, typos, synonyms, category):
    """{value: (spelling, kind)} for one unit's values {value: records}."""
    keyed = [(v, n, spelling_key(unit, v)) for v, n in values.items()]
    keys = {k for _, _, k in keyed}
    pairs = [(spelling_key(unit, t["wrong"]), spelling_key(unit, t["correct"]), normal(t["correct"])) for t in typos]
    # A correct spelling the column itself never uses is still a candidate.
    extra = {}
    for a, b, correct in pairs:
        if a in keys and b not in keys and (b not in extra or correct < extra[b]):
            extra[b] = correct
    spellings = keyed + [(correct, 0, b) for b, correct in extra.items()]
    nodes = {k for _, _, k in spellings}
    typo_edges = {(a, b) for a, b, _ in pairs if a in nodes and b in nodes}
    edges = set(typo_edges)
    sets = collections.defaultdict(set)
    for s in synonyms:
        k = spelling_key(unit, s["spelling"])
        if k in nodes:
            sets[s["synonym_set"]].add(k)
    for members in sets.values():
        edges |= {(k, min(members)) for k in members}
    # Joined sets: each key's root is the smallest key it reaches.
    parent = {k: k for k in nodes}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    wrong = {a for a, _ in typo_edges}
    groups = collections.defaultdict(list)
    for v, n, k in spellings:
        groups[find(k)].append({"value": v, "records": n, "k": k, "wrong": k in wrong, "normal": normal(v)})
    category_keys = collections.defaultdict(list)
    for c in category:
        category_keys[key_text(c)].append(normal(c))
    measure = "unit" in unit.partition(".")[2].lower()
    out = {}
    for members in groups.values():
        if len({m["normal"] for m in members}) <= 1 and all(m["value"] == m["normal"] for m in members):
            continue
        named = [c for m in members for c in category_keys.get(m["k"], [])]
        if named:
            target = min(named)
        else:
            right = [m for m in members if not m["wrong"]] or members
            totals = collections.Counter()
            for m in right:
                totals[m["normal"]] += m["records"]
            target = min(totals, key=lambda s: (unit_distance(s) if measure else title_distance(s), -totals[s], s))
        for m in members:
            if m["value"] == target or m["records"] == 0:
                continue
            if m["normal"].lower() == target.lower() or m["k"] == spelling_key(unit, target):
                kind = "capitals" if m["normal"] != target and m["normal"].lower() == target.lower() else "spaces"
            else:
                kind = "typo" if m["wrong"] else "synonym"
            out[m["value"]] = (target, kind)
    return out


def merges(cur):
    """{(table, column, value): (spelling, kind)}: every DB167 value the rule spells otherwise."""
    kinds = choice_columns()
    cur.execute("select table_name, column_name from information_schema.columns where table_schema = 'raw'")
    present = set(cur.fetchall())
    columns = {c: unit for c, unit in kinds.items() if c in present}
    values = raw_values(cur, columns)
    category = categories(cur)
    typos, synonyms = collections.defaultdict(list), collections.defaultdict(list)
    for t in seed("typos"):
        if (t["table_name"], t["column_name"]) in kinds:
            typos[kinds[(t["table_name"], t["column_name"])]].append(t)
    for s in seed("synonyms"):
        if (s["table_name"], s["column_name"]) in kinds:
            synonyms[kinds[(s["table_name"], s["column_name"])]].append(s)
    doug = {key_text(r["Sub-Area Database Entries"]): r["Corrected Sub-Area"] for r in seed("sub_areas")}
    by_unit = {}
    for unit, vals in values.items():
        corrected = {}
        if unit == "DailyEffortT.Sub-area":
            corrected = {v: doug[key_text(v)] for v in vals if key_text(v) in doug}
        rest = {v: n for v, n in vals.items() if v not in corrected}
        by_unit[unit] = unit_merges(unit, rest, typos[unit], synonyms[unit], category.get(unit, []))
        by_unit[unit].update({v: (to, "corrected") for v, to in corrected.items() if v != to})
    return {(table, column, v): m for (table, column), unit in columns.items() for v, m in by_unit.get(unit, {}).items()}
