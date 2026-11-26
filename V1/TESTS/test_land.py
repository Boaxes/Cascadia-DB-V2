"""The Sightings on Land filter and the loader behind it.

The land test is checked against literal positions chosen on purpose, so it
does not depend on what the seed data happens to hold. The three choices are
checked against a plain query that does not use the filter's cell lookup.
"""

from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.http import QueryDict
from django.test import TestCase

from survey import filters
from survey.export_stack import label
from survey.models import Sighting
from TESTS.test_filters import FilterTest, efforts_with_sightings, one_column


def on_land(lat, lon, margin=filters.LAND_MARGIN_METRES):
    """The filter's own condition, asked about one position."""
    sql = filters._ON_LAND.replace(f", {filters.LAND_MARGIN_METRES})", f", {margin})")
    point = f"ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)"
    return one_column("SELECT " + sql.replace("%(expressions)s", point))[0]


def on_land_sql(geom):
    """Sightings on land, written out again here. The land pieces are looked up
    by cell, which the position tests above check against known places."""
    return f"""
        EXISTS (SELECT 1 FROM public.land_area la
                WHERE la.cell = floor(ST_X({geom}) + 180)::int * 1000 + floor(ST_Y({geom}) + 90)::int
                  AND ST_Intersects(la.geom, {geom}))
        AND NOT EXISTS (SELECT 1 FROM public.land_coast lc
                        WHERE ST_DWithin(lc.geom, {geom}::geography, {filters.LAND_MARGIN_METRES}))"""


def coastal_land_point(metres):
    """A position on land about `metres` from the coast: a point of the coast
    moved inland, tried in each compass direction until one is on land."""
    with connection.cursor() as cur:
        cur.execute("""SELECT ST_Y(ST_StartPoint(geom::geometry)), ST_X(ST_StartPoint(geom::geometry))
                       FROM public.land_coast
                       WHERE ST_Y(ST_StartPoint(geom::geometry)) BETWEEN 30 AND 60
                       ORDER BY id LIMIT 200""")
        starts = cur.fetchall()
        for lat, lon in starts:
            for azimuth in range(0, 360, 45):
                cur.execute("""SELECT ST_Y(p::geometry), ST_X(p::geometry) FROM
                               (SELECT ST_Project(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                                  %s, radians(%s)) AS p) q""",
                            [lon, lat, metres, azimuth])
                y, x = cur.fetchone()
                if on_land(y, x, margin=0):
                    return y, x
    raise AssertionError("no coastal land point found")


class LandConditionTests(TestCase):

    def test_open_sea_is_not_land(self):
        self.assertFalse(on_land(45.0, -150.0))
        self.assertFalse(on_land(0.0, -140.0))

    def test_deep_inland_is_land(self):
        self.assertTrue(on_land(45.0, -110.0))
        self.assertTrue(on_land(50.0, 10.0))

    def test_a_position_near_the_coast_is_not_counted(self):
        lat, lon = coastal_land_point(200)
        self.assertTrue(on_land(lat, lon, margin=0))        # inside the polygon
        self.assertFalse(on_land(lat, lon))                 # but within the margin
        self.assertFalse(on_land(lat, lon, margin=500))
        self.assertTrue(on_land(lat, lon, margin=50))       # a narrower margin counts it

    def test_a_missing_position_is_not_land(self):
        self.assertFalse(one_column("SELECT " + filters._ON_LAND.replace("%(expressions)s", "NULL::geometry"))[0])


class LandFilterTests(FilterTest):

    def count(self, land):
        query = "research_group=all&include_non_animal=1" + (f"&land={land}" if land else "")
        return self.sightings(query)

    def raw(self, condition):
        return one_column(f"SELECT count(*) FROM sighting WHERE {condition}")[0]

    def test_include_changes_nothing(self):
        self.assertEqual(self.count(""), Sighting.objects.count())

    def test_only_and_exclude_split_the_sightings(self):
        total = Sighting.objects.count()
        only, exclude = self.count("only"), self.count("exclude")
        self.assertEqual(only, self.raw(on_land_sql("sighting.geom")))
        self.assertEqual(exclude, total - only)

    def test_sightings_with_no_position_are_kept_by_exclude_and_left_out_of_only(self):
        no_position = self.raw("geom IS NULL")
        self.assertGreaterEqual(self.count("exclude"), no_position)
        self.assertEqual(self.raw(f"geom IS NULL AND ({on_land_sql('sighting.geom')})"), 0)

    def test_other_values_are_ignored(self):
        self.assertEqual(self.count("nonsense"), self.count(""))

    def test_the_other_filters_still_apply(self):
        query = "research_group=CRC&include_non_animal=1&land="
        crc = self.sightings(query)
        self.assertEqual(self.sightings(query + "only") + self.sightings(query + "exclude"), crc)

    def test_efforts_follow_when_matching_is_on(self):
        def efforts(query):
            return self.client.get("/explore/?" + query).context["effort_count"]
        wanted = len(efforts_with_sightings(on_land_sql("sighting.geom")))
        self.assertEqual(efforts("research_group=all&land=only"), wanted)
        every = efforts("research_group=all&land=only&match_sightings=0")
        self.assertEqual(every, efforts("research_group=all"))
        self.assertGreaterEqual(every, wanted)

    def test_the_choice_reaches_the_applied_text_and_the_export_label(self):
        context = self.client.get("/sightings/?research_group=all&land=only").context
        self.assertIn("only sightings on land", str(context["applied"]))
        for choice, text in (("exclude", "Not On Land"), ("only", "Only On Land")):
            self.assertIn(text, label("sightings", f"research_group=all&land={choice}"))
            self.assertTrue(filters.sighting_filter_active(QueryDict(f"land={choice}")))
        self.assertFalse(filters.sighting_filter_active(QueryDict("land=")))

    def test_the_panel_offers_the_three_choices(self):
        html = self.client.get("/sightings/").content.decode()
        self.assertIn("Sightings on Land", html)
        self.assertIn('<option value="">Include</option>', html)
        self.assertIn('value="exclude"', html)
        self.assertIn('value="only"', html)
        self.assertNotIn('name="land"', self.client.get("/efforts/").content.decode())

    def test_missing_tables_give_a_plain_error(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE public.land_area, public.land_coast")
        with self.assertRaises(ValueError) as caught:
            filters.filter_sightings(Sighting.objects.all(), QueryDict("land=only"))
        self.assertIn("load_land", str(caught.exception))
        # Include needs no tables.
        filters.filter_sightings(Sighting.objects.all(), QueryDict(""))


class LoaderTests(TestCase):

    def load(self):
        out = StringIO()
        call_command("load_land", stdout=out)
        return out.getvalue()

    def counts(self):
        return (one_column("SELECT count(*) FROM public.land_area")[0],
                one_column("SELECT count(*) FROM public.land_coast")[0])

    def test_loading_again_does_nothing(self):
        before = self.counts()
        self.assertGreater(before[0], 0)
        self.assertGreater(before[1], 0)
        newest = one_column("SELECT max(id) FROM public.land_area")[0]
        self.assertIn("already loaded", self.load())
        self.assertEqual(self.counts(), before)
        self.assertEqual(one_column("SELECT max(id) FROM public.land_area")[0], newest)

    def test_a_different_version_is_loaded_again(self):
        before = self.counts()
        with connection.cursor() as cur:
            cur.execute("COMMENT ON TABLE public.land_area IS 'an older file'")
        self.assertIn("Loaded", self.load())
        self.assertEqual(self.counts(), before)
        self.assertIn("already loaded", self.load())

    def test_empty_tables_are_loaded(self):
        before = self.counts()
        with connection.cursor() as cur:
            cur.execute("TRUNCATE public.land_area, public.land_coast")
        self.assertIn("Loaded", self.load())
        self.assertEqual(self.counts(), before)
