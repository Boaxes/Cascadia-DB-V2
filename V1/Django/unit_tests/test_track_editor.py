"""The Track File Manager's editor: the line numbers beside the text."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from django.test import SimpleTestCase

STATIC = Path(__file__).resolve().parents[1] / "static" / "survey"


def rule(selector):
    """The declarations of the stylesheet rule whose selector is exactly `selector`."""
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(), flags=re.S)
    found = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return found.group(1) if found else None


def run_script(expression):
    """What a function of track-lines.js returns for `expression`, run in node."""
    if not shutil.which("node"):
        raise unittest.SkipTest("node is not installed")
    script = ("global.window = {}; require(process.argv[1]); const esc = s => String(s ?? '');"
              "process.stdout.write(String(%s));" % expression)
    return subprocess.run(["node", "-e", script, str(STATIC / "track-lines.js")],
                          capture_output=True, text=True, check=True).stdout


class GutterTests(SimpleTestCase):

    def gutter_html(self, count, bad):
        return run_script("window.gutterHtml(%d, %s)" % (count, json.dumps(bad)))

    def test_every_number_is_its_own_block_with_nothing_between_them(self):
        html = self.gutter_html(6, {3: 1, 4: 1})
        # No newline or other text between the blocks: a newline after a block
        # in a pre is a row of its own, which pushed the numbers below a bad
        # line down one row.
        self.assertEqual(re.sub(r'<span class="n( bad)?">\d+</span>', "", html), "")
        self.assertEqual(re.findall(r'<span class="(n(?: bad)?)">(\d+)</span>', html),
                         [("n", "1"), ("n", "2"), ("n bad", "3"), ("n bad", "4"), ("n", "5"), ("n", "6")])

    def test_a_number_is_one_18px_row_bad_or_not(self):
        number, bad, gutter = rule(".gutter .n"), rule(".gutter .bad"), rule(".gutter")
        self.assertIn("display: block", number)
        self.assertIn("height: 18px", number)
        self.assertIn("/18px", gutter)         # the text's own line height
        # A bad number is only coloured: nothing that changes the height of its row.
        for height_changers in ("display", "height", "line-height", "font-size", "border", "padding: 2", "margin: 2"):
            self.assertNotIn(height_changers, bad)
        self.assertRegex(bad, r"padding: 0 \d+px 0 \d+px")
        self.assertRegex(bad, r"margin: 0 -\d+px 0 -\d+px")


class HistoryPanelTests(SimpleTestCase):

    FOOTER = "Restore loads the file as it was before that change"

    def panel(self, rows):
        return run_script("window.historyHtml(%s, esc)" % json.dumps(rows))

    def test_the_footer_shows_when_a_row_has_a_restore_button(self):
        html = self.panel([{"at": "2026-10-20T09:00:00", "who": "A", "what": "Save", "note": None, "version": "v1"},
                           {"at": "2026-10-19T09:00:00", "who": "B", "what": "Fill", "note": None, "version": None}])
        self.assertEqual(html.count("Restore</button>"), 1)
        self.assertIn(self.FOOTER, html)

    def test_the_footer_is_left_out_when_no_row_has_one(self):
        html = self.panel([{"at": "2026-10-20T09:00:00", "who": "A", "what": "Import", "note": "x", "version": None}])
        self.assertNotIn("Restore", html)
        self.assertIn("<table", html)

    def test_a_file_with_no_changes_says_so(self):
        html = self.panel([])
        self.assertIn("No changes have been made", html)
        self.assertNotIn(self.FOOTER, html)
