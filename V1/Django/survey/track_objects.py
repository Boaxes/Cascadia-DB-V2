"""Reading the GPS files out of object storage, DigitalOcean Spaces.

The bucket holds the cleaned files and is the source of truth for them. This
module only ever reads. Uploading is the admin panel's Track file tool, which
is the one thing allowed to write.

Three ways in, and the first one that is configured wins:

- SPACES_LOCAL_DIR, a folder standing in for the bucket, one file per key.
  The tests use it, so an upload in a test never reaches the real bucket.
- SPACES_URL, the base URL of a publicly readable bucket. Nothing secret
  is involved, so there is nothing to leak and nothing to rotate.
- SPACES_ENDPOINT with a key and secret, for a private bucket.

With neither set an export still works and simply carries no tracks folder,
rather than failing.
"""

import hashlib
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

BUCKET = os.environ.get("SPACES_BUCKET", "gps-tracks")
BASE_URL = os.environ.get("SPACES_URL", "").rstrip("/")
ENDPOINT = os.environ.get("SPACES_ENDPOINT", "")
KEY = os.environ.get("SPACES_KEY", "")
SECRET = os.environ.get("SPACES_SECRET", "")
# Put in front of every key written. Empty on the server; a local copy sets it
# (test/) so testing an upload lands beside the real files, never on them.
PREFIX = os.environ.get("SPACES_PREFIX", "")

TIMEOUT = 20


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
    if _local():
        _local_path(key).write_bytes(body)
        return _etag(body)
    response = _client().put_object(Bucket=BUCKET, Key=PREFIX + key, Body=body,
                                    ContentType="text/csv")
    return response["ETag"].strip('"')


def delete(key):
    """Remove one file this application uploaded, when that upload is undone.

    Only ever called by undo, for a file the audit log says was uploaded
    through the track tool; nothing else deletes from the bucket.
    """
    if not can_write():
        raise RuntimeError("Object storage has no key, so nothing can be "
                           "removed.")
    if _local():
        _local_path(key).unlink(missing_ok=True)
        return
    _client().delete_object(Bucket=BUCKET, Key=PREFIX + key)
