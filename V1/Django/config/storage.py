import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class DevStaticStorage(StaticFilesStorage):
    """Local development only: every static URL carries ?v=<modified time>.

    Production hashes file contents into the name (see STORAGES in
    settings). Locally the names are plain, so the browser kept serving the
    old app.css after it was edited. The version makes an edited file a new
    URL, which the browser has to fetch.
    """

    def url(self, name):
        url = super().url(name)
        path = finders.find(name)
        return f"{url}?v={int(os.path.getmtime(path))}" if path else url
