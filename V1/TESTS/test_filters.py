"""The filters Doug asked for: Research Group (CRC by default), Sub-Area,
Project/Objective, and Efforts or Sightings with or without Tags and Samples.

Each count is checked against a plain query written apart from the filter
code, so a mistake in one is not repeated in the other.
"""

from django.core.cache import cache
from django.db import connection
from django.test import TestCase

from survey.models import DailyEffort, Sighting, Track
from survey.services import filter_options
from TESTS.test_permissions import sign_in


def one_column(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


# Efforts named by a row of the table, directly or through one of their
# sightings, and sightings named by a row of it.
def efforts_named_in(table):
    return set(one_column(f'''
        SELECT coalesce(r.daily_effort_id, s.daily_effort_id)
        FROM dbo."{table}" r LEFT JOIN dbo."SightingT" s ON s.id = r.sighting_id'''))


def sightings_named_in(table):
    return set(one_column(f'SELECT sighting_id FROM dbo."{table}" WHERE sighting_id IS NOT NULL'))


class FilterTest(TestCase):

    def setUp(self):
        sign_in(self.client, "viewer", "Viewer")

    def efforts(self, query=""):
        """How many efforts the Efforts list says match."""
        return self.client.get("/efforts/?" + query).context["page"].paginator.count

    def sightings(self, query=""):
        return self.client.get("/sightings/?" + query).context["page"].paginator.count


class ResearchGroupTests(FilterTest):

    def test_crc_is_shown_by_default(self):
        crc = DailyEffort.objects.filter(research_group="CRC").count()
        self.assertGreater(crc, 0)
        self.assertEqual(self.efforts(), crc)
        html = self.client.get("/efforts/").content.decode()
        self.assertIn("Research Group: <strong>CRC (Default)</strong>", html)

    def test_other_groups_are_in_the_data(self):
        self.assertGreater(DailyEffort.objects.exclude(research_group="CRC").count(), 0)

    def test_all_shows_every_group(self):
        self.assertEqual(self.efforts("research_group=all"), DailyEffort.objects.count())
        html = self.client.get("/efforts/?research_group=all").content.decode()
        self.assertIn("All Research Groups", html)

    def test_several_groups(self):
        expected = DailyEffort.objects.filter(research_group__in=["CRC", "AOP"]).count()
        self.assertEqual(self.efforts("research_group=CRC&research_group=AOP"), expected)
        self.assertGreater(expected, self.efforts())

    def test_sightings_follow_their_own_group(self):
        self.assertEqual(self.sightings("research_group=AOP&include_non_animal=1"),
                         Sighting.objects.filter(research_group="AOP").count())

    def test_the_apis_use_the_default_too(self):
        crc = self.client.get("/api/efforts/").json()["total"]
        every = self.client.get("/api/efforts/?research_group=all").json()["total"]
        self.assertEqual(crc, DailyEffort.objects.filter(research_group="CRC").count())
        self.assertEqual(every, DailyEffort.objects.count())

        crc_ids = {row[0] for row in self.client.get("/api/sightings/?include_non_animal=1").json()["rows"]}
        expected = set(Sighting.objects.filter(research_group="CRC", geom__isnull=False)
                       .values_list("legacy_sighting_id", flat=True))
        self.assertEqual(crc_ids, expected)

        aop = len(self.client.get("/api/tracks/?research_group=AOP").json()["features"])
        self.assertEqual(aop, Track.objects.filter(geom__isnull=False,
                                                   daily_effort__research_group="AOP").count())

    def test_the_options_list_every_group_with_its_effort_count(self):
        html = self.client.get("/explore/").content.decode()
        for group in ("CRC", "AOP"):
            count = DailyEffort.objects.filter(research_group=group).count()
            self.assertIn(f'value="{group}"', html)
            self.assertIn(f'data-count="{count}"', html)

    def test_links_between_pages_carry_the_choice(self):
        html = self.client.get("/efforts/?research_group=all").content.decode()
        for url in ('href="/explore/?research_group=all"', 'href="/sightings/?research_group=all"'):
            self.assertIn(url, html)
        effort = DailyEffort.objects.first().legacy_daily_effort_id
        page = self.client.get(f"/efforts/{effort}/?research_group=all").content.decode()
        self.assertIn('href="/efforts/?research_group=all"', page)

    def test_the_default_adds_nothing_to_links(self):
        html = self.client.get("/efforts/").content.decode()
        for url in ('href="/explore/"', 'href="/sightings/"', 'href="/efforts/"'):
            self.assertIn(url, html)


class SubAreaTests(FilterTest):

    def test_several_sub_areas_add_up(self):
        a = self.efforts("research_group=all&sub_area=Southern+California")
        b = self.efforts("research_group=all&sub_area=Washington+Inside+Waters")
        both = self.efforts("research_group=all&sub_area=Southern+California&sub_area=Washington+Inside+Waters")
        self.assertGreater(a, 0)
        self.assertGreater(b, 0)
        self.assertEqual(both, a + b)


class ProjectTests(FilterTest):

    def test_several_projects(self):
        names = ["Opportunistic", "Tagging"]
        query = "research_group=all&project_objective=Opportunistic&project_objective=Tagging"
        self.assertEqual(self.efforts(query),
                         DailyEffort.objects.filter(project_objective__in=names).count())
        self.assertEqual(self.sightings(query),
                         self.sightings("research_group=all&project_objective=Opportunistic")
                         + self.sightings("research_group=all&project_objective=Tagging"))

    def test_the_typos_are_fixed(self):
        self.assertFalse(DailyEffort.objects.filter(project_objective="Opportunstic").exists())


class TagsAndSamplesTests(FilterTest):

    def test_efforts_with_tags_include_those_named_through_a_sighting(self):
        named = efforts_named_in("TagSummaryT")
        expected = DailyEffort.objects.filter(id__in=named).count()
        self.assertEqual(self.efforts("research_group=all&tags=with"), expected)
        self.assertEqual(self.efforts("research_group=all&tags=without"),
                         DailyEffort.objects.count() - expected)

    def test_efforts_with_both_tags_and_samples(self):
        both = efforts_named_in("TagSummaryT") & efforts_named_in("SampleT")
        self.assertEqual(self.efforts("research_group=all&tags=with&samples=with"),
                         DailyEffort.objects.filter(id__in=both).count())

    def test_efforts_with_samples_and_without_tags(self):
        only = efforts_named_in("SampleT") - efforts_named_in("TagSummaryT")
        self.assertEqual(self.efforts("research_group=all&tags=without&samples=with"),
                         DailyEffort.objects.filter(id__in=only).count())

    def test_sightings_with_samples(self):
        named = sightings_named_in("SampleT")
        self.assertEqual(self.sightings("research_group=all&samples=with&include_non_animal=1"),
                         Sighting.objects.filter(id__in=named).count())

    def test_with_tags_combines_with_the_default(self):
        named = efforts_named_in("TagSummaryT")
        self.assertEqual(self.efforts("tags=with"),
                         DailyEffort.objects.filter(id__in=named, research_group="CRC").count())

    def test_the_tracks_api_takes_the_filter(self):
        named = efforts_named_in("TagSummaryT")
        features = self.client.get("/api/tracks/?research_group=all&tags=with").json()["features"]
        expected = Track.objects.filter(geom__isnull=False, daily_effort_id__in=named).count()
        self.assertEqual(len(features), expected)

    def test_anything_else_is_either(self):
        self.assertEqual(self.efforts("tags=maybe"), self.efforts())


class ExportTests(FilterTest):
    """The Export Tool filters with the same code as the lists, so a query
    added to it holds what the list showed. The rest is in test_export.py."""

    def setUp(self):
        sign_in(self.client, "manager", "Data Manager")

    def added(self, kind, query=""):
        self.client.post("/export/add/", {"kind": kind, "qs": query})
        return self.client.get("/export/").context["queries"][-1]

    def test_the_export_uses_the_default(self):
        efforts = self.efforts()
        query = self.added("efforts")
        self.assertEqual(query["efforts"], efforts)
        self.assertEqual(query["efforts"], DailyEffort.objects.filter(research_group="CRC").count())
        self.assertEqual(query["label"], "Efforts: CRC")

    def test_the_export_follows_the_choice(self):
        query = self.added("efforts", "research_group=all")
        self.assertEqual(query["efforts"], DailyEffort.objects.count())
        self.assertEqual(query["label"], "Efforts: All Research Groups")

    def test_an_explore_entry_already_in_a_session_still_resolves(self):
        query = self.added("explore", "research_group=AOP&include_non_animal=1")
        self.assertEqual(query["sightings"], self.sightings("research_group=AOP&include_non_animal=1"))
        self.assertEqual(query["efforts"], self.efforts("research_group=AOP"))

    def test_explore_tab_buttons_match_the_list_pages(self):
        # The Explore page posts "sightings" and "efforts" with its filter
        # string; each must hold what the list page of that kind holds.
        query = "research_group=AOP&include_non_animal=1"
        self.assertEqual(self.added("sightings", query)["sightings"], self.sightings(query))
        self.assertEqual(self.added("efforts", query)["efforts"], self.efforts(query))
        html = self.client.get("/explore/?" + query).content.decode()
        self.assertRegex(html, r'name="kind" value="sightings"\s*>\s*<input type="hidden" name="qs" value="research_group=AOP&amp;include_non_animal=1"')

    def test_efforts_added_from_explore_are_those_with_the_matching_sightings(self):
        species = busiest_species()
        query = self.added("explore", f"research_group=all&species={species}")
        self.assertEqual(query["efforts"], len(efforts_with_sightings(f"species_id = {species}")))
        self.assertEqual(query["sightings"], self.sightings(f"research_group=all&species={species}"))
        every = self.added("explore", f"research_group=all&species={species}&match_sightings=0")
        self.assertEqual(every["efforts"], DailyEffort.objects.count())
        self.assertIn("All Efforts", every["label"])

    def test_sub_area_and_tags_reach_the_export(self):
        query = "research_group=all&sub_area=Southern+California&tags=with"
        self.assertEqual(self.added("efforts", query)["efforts"], self.efforts(query))
        self.assertEqual(self.added("sightings", query)["sightings"], self.sightings(query))

    def test_the_export_label_says_which(self):
        def label(query):
            return self.added("sightings", query)["label"]
        self.assertIn("Species Uncertain Only", label("research_group=all&uncertain=only"))
        self.assertIn("Species Uncertain Only", label("research_group=all&uncertain=1"))
        self.assertIn("Species Uncertain Excluded", label("research_group=all&uncertain=exclude"))
        self.assertNotIn("Uncertain", label("research_group=all"))


class FacetCountTests(FilterTest):
    """The numbers beside each picker option follow the query, and each
    picker ignores its own choice."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def options(self, query="", page="explore"):
        return self.client.get(f"/{page}/?{query}").context["options"]

    def species_counts(self, query=""):
        return {s["id"]: s["count"] for s in self.options(query)["species"]}

    def test_counts_cover_the_default_and_change_with_a_filter(self):
        crc = (Sighting.objects.filter(research_group="CRC")
               .exclude(species__category="non_animal").exclude(species__isnull=True))
        self.assertEqual(sum(self.species_counts().values()), crc.count())
        first = crc.order_by("sighting_date").first().sighting_date
        narrow = crc.filter(sighting_date=first)
        counts = self.species_counts(f"date_from={first}&date_to={first}")
        self.assertEqual(sum(counts.values()), narrow.count())
        self.assertLess(narrow.count(), crc.count())

    def test_uncertain_only_counts_the_uncertain_sightings(self):
        expected = (Sighting.objects.filter(research_group="CRC", species_uncertain=True)
                    .exclude(species__category="non_animal").exclude(species__isnull=True).count())
        self.assertEqual(sum(self.species_counts("uncertain=1").values()), expected)

    def test_a_picker_ignores_its_own_selection(self):
        everything = self.species_counts()
        picked = max(everything, key=everything.get)
        with_pick = self.species_counts(f"species={picked}")
        self.assertEqual(with_pick, everything)
        # The vessel list does follow the species choice: it counts the
        # efforts that have a sighting of the species.
        vessels = {v["id"]: v["efforts"] for v in self.options(f"species={picked}")["vessels"]}
        with_species = Sighting.objects.filter(research_group="CRC", species_id=picked)
        expected = {}
        for vessel in (DailyEffort.objects
                       .filter(research_group="CRC", pk__in=with_species.values("daily_effort_id"))
                       .exclude(vessel_id=None).values_list("vessel_id", flat=True)):
            expected[vessel] = expected.get(vessel, 0) + 1
        self.assertEqual({k: v for k, v in vessels.items() if v}, expected)

    def test_vessels_are_counted_by_effort_on_every_page(self):
        for page in ("explore", "sightings", "efforts"):
            vessels = {v["id"]: v["efforts"] for v in self.options("", page)["vessels"]}
            for vessel, n in vessels.items():
                self.assertEqual(
                    n, DailyEffort.objects.filter(research_group="CRC", vessel_id=vessel).count())
        html = self.client.get("/explore/").content.decode()
        busiest = self.options()["vessels"][0]
        self.assertIn(f'<option value="{busiest["id"]}" data-count="{busiest["efforts"]}"', html)

    def test_research_group_counts_ignore_the_default(self):
        groups = {g["id"]: g["efforts"] for g in self.options("research_group=AOP")["research_groups"]}
        for group in ("CRC", "AOP"):
            self.assertEqual(groups[group], DailyEffort.objects.filter(research_group=group).count())

    def test_ordering_follows_the_counts_with_zeros_last(self):
        cached = filter_options()
        first = Sighting.objects.filter(research_group="CRC").order_by("sighting_date").first()
        options = self.options(f"date_from={first.sighting_date}&date_to={first.sighting_date}")
        self.assertEqual(len(options["species"]), len(cached["species"]))
        self.assertEqual(len(options["vessels"]), len(cached["vessels"]))
        by_group = {}
        for s in options["species"]:
            by_group.setdefault(s["group"], []).append(s["count"])
        for counts in by_group.values():
            self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertIn(0, [s["count"] for s in options["species"]])
        vessels = [v["efforts"] for v in options["vessels"]]
        self.assertEqual(vessels, sorted(vessels, reverse=True))
        groups = [g["efforts"] for g in options["research_groups"]]
        self.assertEqual(groups, sorted(groups, reverse=True))
        self.assertEqual(len(options["research_groups"]), len(cached["research_groups"]))

    def test_a_selected_option_stays_listed_and_selected(self):
        zero = [s["id"] for s in self.options("date_from=1900-01-01&date_to=1900-01-02")["species"]][0]
        html = self.client.get(f"/explore/?date_from=1900-01-01&date_to=1900-01-02&species={zero}").content.decode()
        self.assertRegex(html, rf'<option value="{zero}" data-count="0"[^>]*selected')

    def test_the_group_headings_follow_the_counts(self):
        options = self.options("uncertain=1")
        for group in options["species_groups"]:
            self.assertEqual(group["count"], sum(
                s["count"] for s in options["species"] if s["group"] == group["key"]))

    def test_the_cached_options_are_not_changed(self):
        before = [s["count"] for s in filter_options()["species"]]
        self.options("uncertain=1")
        self.assertEqual([s["count"] for s in filter_options()["species"]], before)

    def test_a_bad_filter_still_renders_the_page(self):
        self.assertEqual(self.client.get("/explore/?area=nonsense").status_code, 200)


def efforts_with_sightings(condition):
    """Ids of efforts with at least one sighting meeting a plain SQL condition."""
    return set(one_column(
        f"SELECT DISTINCT daily_effort_id FROM sighting WHERE daily_effort_id IS NOT NULL AND {condition}"))


def busiest_species():
    return one_column("""SELECT species_id FROM sighting WHERE daily_effort_id IS NOT NULL
                         AND species_id IS NOT NULL GROUP BY species_id
                         ORDER BY count(*) DESC LIMIT 1""")[0]


class MatchingSightingsTests(FilterTest):
    """With a sighting filter set, efforts are those with a matching sighting,
    unless Only Efforts With Matching Sightings is unticked."""

    def explore(self, query):
        context = self.client.get("/explore/?" + query).context
        return context["sighting_count"], context["effort_count"]

    def test_ticked_narrows_efforts_to_those_with_a_matching_sighting(self):
        species = busiest_species()
        wanted = efforts_with_sightings(f"species_id = {species}")
        _sightings, efforts = self.explore(f"research_group=all&species={species}")
        self.assertEqual(efforts, len(wanted))
        self.assertLess(efforts, DailyEffort.objects.count())

    def test_the_other_effort_filters_still_apply(self):
        species = busiest_species()
        wanted = efforts_with_sightings(f"species_id = {species}")
        in_group = set(DailyEffort.objects.filter(research_group="CRC").values_list("pk", flat=True))
        _sightings, efforts = self.explore(f"research_group=CRC&species={species}")
        self.assertEqual(efforts, len(wanted & in_group))

    def test_uncertain_species_narrows_too(self):
        wanted = efforts_with_sightings("species_uncertain")
        _sightings, efforts = self.explore("research_group=all&uncertain=only")
        self.assertEqual(efforts, len(wanted))
        self.assertEqual(self.explore("research_group=all&uncertain=1")[1], len(wanted))

    def test_excluding_uncertain_species_narrows_efforts_to_the_rest(self):
        wanted = efforts_with_sightings("species_uncertain IS NOT TRUE")
        _sightings, efforts = self.explore("research_group=all&uncertain=exclude")
        self.assertEqual(efforts, len(wanted))
        every = DailyEffort.objects.count()
        self.assertEqual(self.explore("research_group=all&uncertain=exclude&match_sightings=0")[1], every)

    def test_including_uncertain_species_is_not_a_sighting_filter(self):
        every = DailyEffort.objects.filter(research_group="CRC").count()
        self.assertEqual(self.explore("research_group=CRC&uncertain=")[1], every)


    def test_unticked_lists_every_effort_the_effort_filters_match(self):
        species = busiest_species()
        every = DailyEffort.objects.filter(research_group="CRC").count()
        self.assertEqual(self.explore(f"research_group=CRC&species={species}&match_sightings=0")[1], every)
        self.assertEqual(self.explore(f"research_group=CRC&species={species}&match_sightings=0&match_sightings=1")[1],
                         self.explore(f"research_group=CRC&species={species}")[1])

    def test_no_sighting_filter_changes_nothing(self):
        every = DailyEffort.objects.filter(research_group="CRC").count()
        self.assertEqual(self.explore("research_group=CRC")[1], every)
        self.assertEqual(self.explore("research_group=CRC&match_sightings=0")[1], every)
        # The default hiding of non-animal records is not a sighting filter.
        self.assertEqual(self.explore("")[1], every)
        self.assertEqual(self.efforts("research_group=CRC"), every)

    def test_the_effort_api_and_the_tracks_follow(self):
        species = busiest_species()
        query = f"research_group=all&species={species}"
        narrowed = len(efforts_with_sightings(f"species_id = {species}"))
        self.assertEqual(self.client.get("/api/efforts/?" + query).json()["total"], narrowed)
        self.assertEqual(self.client.get("/api/efforts/?" + query + "&match_sightings=0").json()["total"],
                         DailyEffort.objects.count())


class UncertainSpeciesTests(FilterTest):
    """Include (the default), Exclude and Only, and the old checkbox link."""

    def count(self, choice):
        query = "research_group=all&include_non_animal=1" + (f"&uncertain={choice}" if choice else "")
        return self.sightings(query)

    def test_the_three_choices(self):
        uncertain = Sighting.objects.filter(species_uncertain=True).count()
        everything = Sighting.objects.count()
        # The CI seed may hold no uncertain sightings; the three still have to add up.
        self.assertEqual(self.count(""), everything)
        self.assertEqual(self.count("only"), uncertain)
        self.assertEqual(self.count("exclude"), everything - uncertain)

    def test_exclude_keeps_rows_where_the_flag_is_null(self):
        wanted = one_column("SELECT count(*) FROM sighting WHERE species_uncertain IS NOT TRUE")[0]
        self.assertEqual(self.count("exclude"), wanted)

    def test_the_old_link_means_only(self):
        self.assertEqual(self.count("1"), self.count("only"))
        html = self.client.get("/sightings/?research_group=all&uncertain=1").content.decode()
        self.assertRegex(html, r'<option value="only"\s+selected')

    def test_the_select_shows_the_choice(self):
        html = self.client.get("/sightings/?uncertain=exclude").content.decode()
        self.assertRegex(html, r'<option value="exclude"\s+selected')
        self.assertIn('<option value="">Include</option>', html)
