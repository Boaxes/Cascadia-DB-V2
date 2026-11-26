"""
Two things a request can show that the log should hold: being refused (403) and
being slow. Everything else a request does is written where it happens. Each
request is also the moment to take a reading of the machine for the Server
page's graph, if a minute has passed since the last (datahealth/serverhealth.py).

A refusal is worth a line because a person with the wrong permission trying a
page, or a form posted without its token, is what someone looking for trouble
looks like. Slowness is worth a line because the first sign of a struggling
server is a page that takes a long time. Pages that are slow on purpose (the
export, an upload) are left out of the second.
"""

import time

from . import events, serverhealth

# Seconds before a request is called slow.
SLOW_SECONDS = 10
LONG_BY_DESIGN = ("/export/download/", "/cascadia-admin/tracks/api/import/")


class ServerEventMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        elapsed = time.monotonic() - started
        if response.status_code == 403:
            events.record("security", "access_denied", request=request,
                          message=f"{request.method} {request.path} was refused.", method=request.method)
        elif (elapsed >= SLOW_SECONDS
              and not request.path.startswith(LONG_BY_DESIGN)):
            events.record("server", "slow_request", request=request,
                          message=f"{request.method} {request.path} took {elapsed:.1f} seconds.",
                          method=request.method, seconds=round(elapsed, 1), status=response.status_code)
        # A reading of the machine for the Server page's graph, when a minute has passed.
        serverhealth.maybe_sample()
        return response
