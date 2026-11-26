"""The Research Group filter's choice, and how it is carried from page to page."""

from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase

from survey.context_processors import research_group_query
from survey.filters import research_group_choice


class ResearchGroupChoiceTests(SimpleTestCase):

    def test_nothing_chosen_is_crc_by_default(self):
        choice = research_group_choice(QueryDict(""))
        self.assertEqual(choice, {"groups": ["CRC"], "default": True, "label": "CRC (Default)"})

    def test_all_removes_the_filter(self):
        choice = research_group_choice(QueryDict("research_group=all"))
        self.assertIsNone(choice["groups"])
        self.assertEqual(choice["label"], "All Research Groups")

    def test_all_wins_over_any_group_beside_it(self):
        self.assertIsNone(research_group_choice(QueryDict("research_group=AOP&research_group=all"))["groups"])

    def test_several_groups_once_each_in_the_order_chosen(self):
        choice = research_group_choice(QueryDict("research_group=AOP&research_group=CRC&research_group=AOP"))
        self.assertEqual(choice["groups"], ["AOP", "CRC"])
        self.assertFalse(choice["default"])
        self.assertEqual(choice["label"], "AOP, CRC")

    def test_a_long_choice_is_shortened_in_the_label(self):
        query = "&".join(f"research_group={g}" for g in ["A", "B", "C", "D", "E"])
        self.assertEqual(research_group_choice(QueryDict(query))["label"], "A, B, C and 2 more")

    def test_empty_values_count_as_nothing_chosen(self):
        self.assertTrue(research_group_choice(QueryDict("research_group=&research_group=+"))["default"])


class ResearchGroupLinkTests(SimpleTestCase):

    def query(self, url):
        return research_group_query(RequestFactory().get(url))["research_group_query"]

    def test_the_default_adds_nothing_to_links(self):
        self.assertEqual(self.query("/efforts/"), "")
        self.assertEqual(self.query("/efforts/?species=3"), "")

    def test_a_choice_is_carried(self):
        self.assertEqual(self.query("/efforts/?research_group=all&species=3"), "?research_group=all")
        self.assertEqual(self.query("/efforts/?research_group=AOP&research_group=NB"),
                         "?research_group=AOP&research_group=NB")
