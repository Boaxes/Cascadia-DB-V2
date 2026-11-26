"""
The test runner for the automatic tests (ETL/ci/steps.sh, `site`).

It is the site's own runner (Django/config/test_runner.py: a fresh copy of the
database named by REFERENCE_DB for every run) with one addition: a list of
tests that cannot run on GitHub, each skipped with a plain message saying why.
Nothing in TESTS/ is changed to do this.

    python manage.py test TESTS --testrunner=ci_runner.CiRunner

A test is named by its dotted path, as the test run prints it, and a prefix
names every test beneath it. Add a line to SKIPS when a test needs something
that only exists on the Mac, and say which thing.
"""

import unittest

from config.test_runner import ReferenceCopyRunner

# a dotted path (or a prefix of one), and the reason the test cannot run here
SKIPS = {
    "TESTS.test_track_manager.ExplorerTests.test_the_explorer_lists_every_file_a_page_at_a_time":
        "it expects more than 1,500 track files, the whole GPS bucket; the seed holds the 23 that go with its records",
}


def _reason(test_id):
    for prefix, why in SKIPS.items():
        if test_id == prefix or test_id.startswith(prefix + "."):
            return why
    return None


def _skip_where_listed(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            _skip_where_listed(test)
            continue
        why = _reason(test.id())
        if why:
            method = getattr(test, test._testMethodName)
            setattr(test, test._testMethodName, unittest.skip(f"Not run in CI: {why}")(method))


class CiRunner(ReferenceCopyRunner):

    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        _skip_where_listed(suite)
        return suite
