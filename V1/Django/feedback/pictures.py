"""Checking an uploaded picture by its first bytes, not by its name or the
browser's say-so."""

MAX_FILES = 3
MAX_BYTES = 5 * 1024 * 1024

# Content type and the extension used in the picture's address.
PNG = ("image/png", "png")
JPEG = ("image/jpeg", "jpg")
GIF = ("image/gif", "gif")
WEBP = ("image/webp", "webp")


def sniff(data):
    """The (content type, extension) of a PNG, JPEG, GIF or WebP, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith((b"GIF87a", b"GIF89a")):
        return GIF
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    return None
