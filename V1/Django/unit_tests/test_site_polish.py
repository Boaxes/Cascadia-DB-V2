"""
How the site writes what people read: no arrow letters, Title Case labels,
and numbers with thousands separators.
"""

import pathlib
import re
from decimal import Decimal

from django.test import RequestFactory, SimpleTestCase

from survey.templatetags import survey_tags

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [ROOT / "templates", ROOT / "datahealth" / "templates"]
SCRIPTS = sorted((ROOT / "static" / "survey").glob("*.js"))

# Arrow letters and their HTML names, and the triangles that stood in for them.
ARROWS = re.compile("[←-⇿▲-◄⬀-⯿]|&[lrud]arr;|&#x2[12][0-9a-f]{2};")


def templates():
    for folder in TEMPLATE_DIRS:
        yield from sorted(folder.rglob("*.html"))


def strip_comments(text):
    text = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=re.S)
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


class NoArrowLettersTests(SimpleTestCase):

    def test_no_template_or_script_writes_an_arrow(self):
        for path in list(templates()) + SCRIPTS:
            text = strip_comments(path.read_text(encoding="utf-8"))
            self.assertIsNone(ARROWS.search(text), path.name)

    def test_the_sort_direction_is_a_chevron(self):
        request = RequestFactory().get("/efforts/", {"sort": "date"})
        for descending, direction in ((True, "down"), (False, "up")):
            context = {"request": request, "sort_key": "date", "sort_desc": descending}
            html = str(survey_tags.sort_header(context, "date", "Date"))
            self.assertIn(f'<i class="sort-ind {direction}"></i>', html)
            self.assertIsNone(ARROWS.search(html))
        other = str(survey_tags.sort_header({"request": request, "sort_key": "id"}, "date", "Date"))
        self.assertNotIn("sort-ind", other)


# The one rule: every word starts with a capital except a, an, the, and, or and
# of, and the first and last word always do. "Survey type" and "Crew member"
# are caught, and so is "Back to the Site".
SMALL = {"a", "an", "the", "and", "or", "of"}
# The templates where another change is under way, and the Export page, which
# has its own wording.
SKIPPED = {"export.html", "tracks.html", "track_fill.html", "track_import.html", "audit.html"}
# A stand-in for a species name is a data value, left as written.
DATA_VALUES = {"Not identified"}
LABEL = re.compile(r"<(label|th|dt|button|h1|h2|h3|summary|option)\b[^>]*>([^<{]*)</\1>", re.I)


# Names of schemas, written as they are in the database.
IDENTIFIERS = {"dbo", "raw", "app"}


def title_case_problem(text):
    """The first word that breaks the rule in a label, or None."""
    words = re.sub(r"\s*\([^)]*\)", "", text).split()
    for i, word in enumerate(words):
        edge = i in (0, len(words) - 1)
        for part in re.findall(r"[A-Za-z][A-Za-z']*", word):
            if part in IDENTIFIERS:
                continue
            if part.lower() in SMALL and not edge:
                if not part.islower():
                    return part
            elif part[0].islower():
                return part
    return None


class TitleCaseTests(SimpleTestCase):

    def test_the_rule_itself(self):
        for good in ("Back To the Site", "Length of the GPS Track", "Open As a List", "Or Else", "Sub-Area",
                     "Table By Table", "Yes or No"):
            self.assertIsNone(title_case_problem(good), good)
        for bad in ("Survey type", "Back to the Site", "Table by Table", "Group Or Both", "Sub-area",
                    "Draw An Area"):
            self.assertIsNotNone(title_case_problem(bad), bad)

    def test_every_plain_label_is_in_title_case(self):
        wrong = []
        for path in templates():
            if path.name in SKIPPED:
                continue
            for match in LABEL.finditer(strip_comments(path.read_text(encoding="utf-8"))):
                text = " ".join(match.group(2).replace("&amp;", "&").replace("&ndash;", "-").split())
                if text in DATA_VALUES:
                    continue
                words = re.findall(r"[A-Za-z][A-Za-z'-]*", re.sub(r"\s*\([^)]*\)", "", text))
                # Single words and sentences are not labels to check.
                if len(words) < 2 or len(words) > 6 or text.endswith((".", "?", "!")) or ":" in text:
                    continue
                if title_case_problem(text):
                    wrong.append(f"{path.name}: {text}")
        self.assertEqual(wrong, [])


    def test_the_map_button_names_follow_the_rule(self):
        script = (ROOT / "static" / "survey" / "basemap.js").read_text(encoding="utf-8")
        names = re.findall(r'(?:Title|title|text|polygon|rectangle|remove|removeDisabled)\s*=\s*"([^"]+)"', script)
        self.assertGreater(len(names), 10)
        for name in names:
            self.assertIsNone(title_case_problem(name), name)


class ThousandsTests(SimpleTestCase):

    def test_a_count_gets_separators(self):
        self.assertEqual(survey_tags.thousands(1049), "1,049")
        self.assertEqual(survey_tags.thousands(1234567), "1,234,567")
        self.assertEqual(survey_tags.thousands(12), "12")
        self.assertEqual(survey_tags.thousands(0), "0")
        self.assertEqual(survey_tags.thousands(-1049), "-1,049")
        self.assertEqual(survey_tags.thousands(1049.0), "1,049")
        self.assertEqual(survey_tags.thousands(Decimal("1049")), "1,049")
        self.assertEqual(survey_tags.thousands("1049"), "1,049")

    def test_a_large_whole_number_is_exact(self):
        self.assertEqual(survey_tags.thousands(2 ** 60 + 1), "1,152,921,504,606,846,977")
        self.assertEqual(survey_tags.thousands(Decimal(10 ** 14 + 1)), "100,000,000,000,001")

    def test_nothing_else_is_touched_and_nothing_raises(self):
        values = [None, "", "   ", "n/a", True, False, float("inf"), float("-inf"), float("nan"),
                  1e300, 2.5, Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("1E+999999999"),
                  Decimal("2.5"), "inf", "nan", "1e999999999", object(), [1], {"a": 1}]
        for value in values:
            with self.subTest(value=repr(value)):
                result = survey_tags.thousands(value)
                if isinstance(value, float) and value != value:
                    self.assertTrue(result != result)
                else:
                    self.assertIs(result, value)
