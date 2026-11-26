"""The Sub-area filter's list, read from Doug's corrections in survey/sub_areas.csv."""

from pathlib import Path

from django.test import SimpleTestCase

from survey import sub_areas


class SubAreaTests(SimpleTestCase):
    def test_each_corrected_name_is_offered_once_north_to_south(self):
        names = [g["name"] for g in sub_areas.GROUPS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[:3], ["Southern British Columbia", "WA/BC Inside Waters", "WA/BC Border region"])

    def test_large_sub_areas_come_first(self):
        values = ["Southern California", "SW Vancouver Is.", "Washington Inside Waters"]
        main, other = sub_areas.choices(values)
        self.assertEqual(main, ["Washington Inside Waters", "Southern California"])
        self.assertEqual(other, ["Vancouver Island"])

    def test_names_with_no_efforts_are_not_offered(self):
        main, other = sub_areas.choices(["Southern California"])
        self.assertEqual((main, other), (["Southern California"], []))

    def test_a_name_matches_every_spelling_under_it(self):
        values = ["So California", "Southern California", "southern california ", "Central California"]
        self.assertEqual(sub_areas.matching_values("Southern California", values),
                         ["So California", "Southern California", "southern california "])

    def test_an_unknown_name_matches_nothing(self):
        self.assertEqual(sub_areas.matching_values("Atlantis", ["Atlantis"]), [])


class SameTableTests(SimpleTestCase):
    """The pipeline corrects Sub-area from its own copy of the table
    (ETL/dbt/seeds/sub_areas.csv); the filter and the data must agree."""

    def test_the_pipeline_uses_the_same_table(self):
        here = Path(sub_areas.__file__).with_name("sub_areas.csv")
        seed = here.parents[2] / "ETL" / "dbt" / "seeds" / "sub_areas.csv"
        if not seed.exists():
            self.skipTest("ETL/ is not in this checkout (the web container mounts Django/ only)")
        self.assertEqual(here.read_bytes(), seed.read_bytes())
