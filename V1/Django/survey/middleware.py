"""Explain an empty local database, instead of showing Django's traceback.

A fresh machine's database has no tables until ops/pull-db.sh has filled it.
The login page still renders, because it reads nothing, so the first sign of
trouble is signing in and getting a ProgrammingError page about auth_user,
which says nothing about the fix. Locally only: in production a missing table
is a real fault and should be reported as one.
"""

from html import escape

from django.conf import settings
from django.db import ProgrammingError
from django.http import HttpResponse

PAGE = """<!doctype html>
<title>Local database is empty</title>
<body style="font-family:system-ui,sans-serif;max-width:40em;margin:3em auto;padding:0 16px;line-height:1.5">
<h1>The local database has no data in it yet</h1>
<p>This copy of the site has nothing to sign in against, because the live
database has not been copied onto this machine, or the copy did not finish.</p>
<p>Open a second terminal in the <code>Cascadia-DB</code> folder (on Windows,
right-click it and choose <b>Open Git Bash here</b>) and run:</p>
<pre style="background:#eee;padding:8px 12px">ops/pull-db.sh</pre>
<p>It prints each step as it goes. If it stops with <b>FAILED</b>, the lines
below that say why. When it says <b>Done</b>, come back here and sign in.</p>
<p style="color:#666">What Postgres said: <code>{error}</code></p>
</body>"""


class EmptyDatabaseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not settings.DEBUG:
            return None
        if isinstance(exception, ProgrammingError) and "does not exist" in str(exception):
            error = escape(str(exception).strip().splitlines()[0])
            return HttpResponse(PAGE.format(error=error), status=503)
        return None
