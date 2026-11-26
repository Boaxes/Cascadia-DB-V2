# Gunicorn reads this from the folder it runs in. Without it a worker is killed after 30 seconds, which a long export outlasts.
timeout = 300


# Say in the server event log when the server starts and stops (the Server page
# of the Django admin). A separate process each time, so the master never opens a database
# connection that its workers would then share. A failure is ignored: logging the
# start must never keep the site from starting.
def _log_event(event, message):
    import subprocess
    import sys
    try:
        subprocess.Popen([sys.executable, "manage.py", "log_server_event", "server", event,
                          "--actor", "Gunicorn", "--message", message],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def when_ready(server):
    _log_event("started", "The website server started and is ready for requests.")


def on_exit(server):
    _log_event("stopped", "The website server stopped.")
