"""Signed-out visitors are sent to sign in, and the home address goes to Explore."""

import pytest
from django.test import Client
from django.urls import reverse

PAGES = [
    "survey:explore",
    "survey:effort_list",
    "survey:sighting_list",
    "photoid:individual_list",
    "analysis:export_page",
    "analysis:sql_page",
    "manage:track_list",
    "manage:audit_list",
    "manage:server_page",
    "core:settings",
    "core:feedback",
]


@pytest.mark.spec("AUTH-02")
@pytest.mark.parametrize("view", PAGES)
def test_signed_out_visitor_is_sent_to_sign_in(client: Client, view: str) -> None:
    url = reverse(view)
    response = client.get(url)
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('core:login')}?next={url}"


@pytest.mark.spec("NAV-05")
def test_home_goes_to_explore(admin_client: Client) -> None:
    response = admin_client.get("/")
    assert response.status_code == 302
    assert response["Location"] == reverse("survey:explore")


@pytest.mark.spec("NAV-01")
@pytest.mark.parametrize("view", PAGES)
def test_every_landing_page_opens_with_the_sidebar(admin_client: Client, view: str) -> None:
    response = admin_client.get(reverse(view))
    assert response.status_code == 200
    assert b'class="sidebar"' in response.content
