"""Reading the GPS files out of object storage, DigitalOcean Spaces.

The bucket holds the cleaned files and is the source of truth for them. This
module mostly reads. The Track File Manager is the one thing allowed to write:
put() adds a file and refuses to replace one, replace() writes a new version
and keeps the old under _versions/, and a deleted file moves to _deleted/.

Three ways in, and the first one that is configured wins:

- SPACES_LOCAL_DIR, a folder standing in for the bucket, one file per key.
  The tests use it, so an upload in a test never reaches the real bucket, and
  a local copy of the site can use it the same way: `manage.py
  download_track_files` fills the folder from the bucket, and from then on
  the site reads and writes the folder and never the bucket.
- SPACES_URL, the base URL of a publicly readable bucket. Nothing secret
  is involved, so there is nothing to leak and nothing to rotate.
- SPACES_ENDPOINT with a key and secret, for a private bucket.

With neither set an export still works and simply carries no tracks folder,
rather than failing.
"""

import datetime
import hashlib
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

from survey import track_checks

BUCKET = os.environ.get("SPACES_BUCKET", "gps-tracks")
BASE_URL = os.environ.get("SPACES_URL", "").rstrip("/")
ENDPOINT = os.environ.get("SPACES_ENDPOINT", "")
KEY = os.environ.get("SPACES_KEY", "")
SECRET = os.environ.get("SPACES_SECRET", "")
# Put in front of every key written. Empty on the server; a local copy sets it
# (test/) so testing an upload lands beside the real files, never on them.
PREFIX = os.environ.get("SPACES_PREFIX", "")

TIMEOUT = 20

# Where a file's earlier versions are kept, and where a deleted file goes.
# Neither is a GPS file in its own right, so listing() leaves both out.
VERSIONS = "_versions/"
DELETED = "_deleted/"
FOLDERS = (VERSIONS, DELETED)


def _local():
    """The folder standing in for the bucket, or None. Read on every call, so
    a test can point it somewhere after this module is imported."""
    folder = os.environ.get("SPACES_LOCAL_DIR", "")
    return pathlib.Path(folder) if folder else None


def _local_path(key):
    folder = _local()
    path = (folder / key).resolve()
    if folder.resolve() not in path.parents:
        raise ValueError(f"{key!r} is not a file name.")
    return path


def _etag(body):
    # What S3 and Spaces give a file uploaded in one piece.
    return hashlib.md5(body).hexdigest()


def configured():
    return bool(_local() or BASE_URL or (ENDPOINT and KEY and SECRET))


def how():
    """Which way in is being used, for the admin panel to report."""
    if _local():
        return f"local folder {_local()}"
    if BASE_URL:
        return f"public bucket at {BASE_URL}"
    if ENDPOINT and KEY and SECRET:
        return f"private bucket at {ENDPOINT}"
    return "not configured"


def _fetch_public(object_keys):
    for key in object_keys:
        url = f"{BASE_URL}/{urllib.parse.quote(key)}"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                yield key, response.read()
        except (urllib.error.URLError, OSError):
            continue


def _client():
    import boto3

    return boto3.client("s3", endpoint_url=ENDPOINT,
                        aws_access_key_id=KEY, aws_secret_access_key=SECRET,
                        region_name=os.environ.get("SPACES_REGION"))


def _fetch_private(object_keys):
    client = _client()
    for key in object_keys:
        # A file uploaded under the prefix first, then the real one.
        for stored in ([PREFIX + key] if PREFIX else []) + [key]:
            try:
                response = client.get_object(Bucket=BUCKET, Key=stored)
            except Exception:
                continue
            yield key, response["Body"].read()
            break


def fetch(object_keys):
    """Yield (name, bytes) for each key that is actually in the bucket.

    A key the bucket does not hold is skipped. 21 track records name a file
    that is not there, and an export of them should still produce the rest.
    """
    if _local():
        for key in object_keys:
            path = _local_path(key)
            if path.is_file():
                yield key, path.read_bytes()
    elif BASE_URL:
        yield from _fetch_public(object_keys)
    elif ENDPOINT and KEY and SECRET:
        yield from _fetch_private(object_keys)


def can_write():
    """Uploading needs a key. A public URL is readable and nothing more."""
    return bool(_local() or (ENDPOINT and KEY and SECRET))


def listing():
    """Every GPS file in the bucket: {key: (stored key, etag, size in bytes)}.

    Keys are as the application names them, without the prefix. Where a file
    exists both under the prefix and without it, the prefixed one wins, the
    same way `fetch` reads it. Anything that is not a CSV is left out.

    The folders of earlier versions and of deleted files are left out too.

    Needs a key: a public base URL can read an object by name but cannot list
    what is there. Used by `manage.py regenerate_track_geometry`.
    """
    if not can_write():
        raise RuntimeError("Listing the bucket needs a key.")
    if _local():
        return {path.name: (path.name, _etag(path.read_bytes()), path.stat().st_size)
                for path in sorted(_local().iterdir())
                if path.is_file() and path.name.lower().endswith(".csv")}
    client = _client()
    found = {}
    token = None
    while True:
        page = client.list_objects_v2(
            **{"Bucket": BUCKET, **({"ContinuationToken": token} if token else {})})
        for item in page.get("Contents", []):
            stored = item["Key"]
            if not stored.lower().endswith(".csv"):
                continue
            if stored[len(PREFIX):].startswith(FOLDERS) or stored.startswith(FOLDERS):
                continue
            prefixed = bool(PREFIX) and stored.startswith(PREFIX)
            key = stored[len(PREFIX):] if prefixed else stored
            if key in found and not prefixed:
                continue
            found[key] = (stored, item["ETag"].strip('"'), item["Size"])
        if not page.get("IsTruncated"):
            return found
        token = page["NextContinuationToken"]


def read(stored_key):
    """One object's bytes, by the exact key it is stored under."""
    if not can_write():
        raise RuntimeError("Reading by exact key needs a key.")
    if _local():
        return _local_path(stored_key).read_bytes()
    return _client().get_object(Bucket=BUCKET, Key=stored_key)["Body"].read()


def exists(key):
    if not can_write():
        return False
    if _local():
        return _local_path(key).is_file()
    try:
        _client().head_object(Bucket=BUCKET, Key=PREFIX + key)
        return True
    except Exception:
        return False


def _store(key, body):
    """Write one object, replacing any there, and return its ETag. put() and
    the functions below, which keep an earlier copy first, are the callers."""
    if _local():
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside it and moved into place, so a file is never seen half
        # written, as in a bucket, whatever the permissions of the one replaced.
        part = path.with_name(path.name + ".part")
        part.write_bytes(body)
        os.replace(part, path)
        etag = _etag(body)
    else:
        response = _client().put_object(Bucket=BUCKET, Key=PREFIX + key, Body=body,
                                        ContentType="text/csv")
        etag = response["ETag"].strip('"')
    # Every GPS file written is checked again (track_checks), whichever change wrote it.
    track_checks.after_write(key, body)
    return etag


def put(key, body):
    """Write one GPS file into the bucket, and return its ETag.

    Refuses to replace a file that is already there. Overwriting is how the
    only authoritative copy of a track gets lost, and there is no undo.
    """
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be "
                           "uploaded.")
    if exists(key):
        raise FileExistsError(f"{key} is already in the bucket.")
    return _store(key, body)


def get(key):
    """One file's bytes, or None when the bucket does not hold it."""
    return dict(fetch([key])).get(key)


def stamped(folder, key):
    """A name in `folder` for a copy of `key` made now: the UTC time, to the
    second, and a number after it if that second is taken."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name, number = f"{folder}{key}/{now}.csv", 1
    while exists(name):
        number += 1
        name = f"{folder}{key}/{now}-{number}.csv"
    return name


def keep_version(key):
    """Copy the file as it is now to _versions/<key>/<UTC timestamp>.csv, and
    return where it went; None when the bucket does not hold it."""
    current = get(key)
    if current is None:
        return None
    kept = stamped(VERSIONS, key)
    _store(kept, current)
    return kept


def replace(key, text):
    """
    Write a new version of a file that is already there, and keep the old one.

    The current file is copied to _versions/<key>/<UTC timestamp>.csv first, so
    nothing is ever lost, then the new text is written. Returns the new ETag and
    the key the old file was kept under. put() still refuses to overwrite: this
    is the one way a file changes.
    """
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be saved.")
    kept = keep_version(key)
    if kept is None:
        raise FileNotFoundError(f"{key} is not in the bucket.")
    try:
        return _store(key, text.encode("utf-8")), kept
    except Exception:
        delete(kept)         # the copy just made, so a failure leaves no stray version
        raise


def restore(key, body):
    """Put back the bytes a failed or undone change replaced. Callers keep a
    copy first (keep_version) when the file as it is now is worth having."""
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be put back.")
    return _store(key, body)


def move(source, destination):
    """Move one object, never over one that is already there."""
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be moved.")
    body = get(source)
    if body is None:
        raise FileNotFoundError(f"{source} is not in the bucket.")
    if exists(destination):
        raise FileExistsError(f"{destination} is already in the bucket.")
    _store(destination, body)
    try:
        delete(source)
    except Exception:
        delete(destination)      # the copy just made, so a failed move leaves one file
        raise


def retire(key):
    """Move a deleted track's file to _deleted/<key>/<UTC timestamp>.csv, and
    return where it went. Nothing is ever hard-deleted."""
    destination = stamped(DELETED, key)
    move(key, destination)
    return destination


def under(folder):
    """The keys stored under one folder, such as _versions/<key>, oldest first."""
    folder = folder.rstrip("/")
    if not can_write():
        return []
    if _local():
        path = _local_path(folder + "/x").parent
        if not path.is_dir():
            return []
        return sorted(f"{folder}/{p.name}" for p in path.iterdir() if p.is_file())
    found, token = [], None
    client = _client()
    while True:
        page = client.list_objects_v2(**{"Bucket": BUCKET, "Prefix": PREFIX + folder + "/",
                                         **({"ContinuationToken": token} if token else {})})
        found += [item["Key"][len(PREFIX):] for item in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return sorted(found)
        token = page["NextContinuationToken"]


def delete(key):
    """Remove one object: a file whose upload is undone, or the old place of
    one that move() has copied. A deleted track's file is moved to _deleted/,
    never removed, so nothing else deletes a GPS file from the bucket.
    """
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be "
                           "removed.")
    if _local():
        _local_path(key).unlink(missing_ok=True)
    else:
        _client().delete_object(Bucket=BUCKET, Key=PREFIX + key)
    track_checks.after_remove(key)


def download(folder, everything=False, report=None):
    """Copy the bucket's GPS files into a folder that can then stand in for the
    bucket (SPACES_LOCAL_DIR). The bucket is only read.

    It always reads the real bucket, even where SPACES_LOCAL_DIR is set, since
    filling that folder is the point. A file already in the folder with the
    same size and contents is left alone, so a run can be repeated or resumed.
    The earlier versions and the deleted files (_versions/, _deleted/) are
    left behind unless `everything` is set: a local copy rarely wants them.

    Returns how many files were (downloaded, already there).
    """
    if not (ENDPOINT and KEY and SECRET):
        raise RuntimeError("Reading the bucket needs SPACES_ENDPOINT, SPACES_KEY "
                           "and SPACES_SECRET.")
    folder = pathlib.Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    client = _client()
    downloaded = unchanged = 0
    token = None
    while True:
        page = client.list_objects_v2(
            **{"Bucket": BUCKET, **({"ContinuationToken": token} if token else {})})
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.lower().endswith(".csv"):
                continue
            # Only the bucket's own files and its two folders: anything else
            # with a folder in its name is a test upload under a prefix.
            kept = key.startswith(FOLDERS)
            if (kept and not everything) or (not kept and "/" in key):
                continue
            path = (folder / key).resolve()
            if folder not in path.parents:
                raise ValueError(f"{key!r} is not a file name.")
            etag = item["ETag"].strip('"')
            if path.is_file() and path.stat().st_size == item["Size"] and (
                    "-" in etag or _etag(path.read_bytes()) == etag):
                unchanged += 1
                continue
            body = client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".part")
            part.write_bytes(body)
            os.replace(part, path)
            downloaded += 1
            if report:
                report(key)
        if not page.get("IsTruncated"):
            return downloaded, unchanged
        token = page["NextContinuationToken"]
