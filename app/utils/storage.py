"""
Local-disk storage for uploaded documents (Notice Reply / Summarizer
attachments). Nothing equivalent existed in the codebase before this —
this is new, minimal, single-purpose infrastructure, not a duplicate of
anything.

Files are stored under UPLOAD_DIR with a UUID-prefixed filename to avoid
collisions and path-traversal from user-supplied filenames. The original
filename is preserved separately (AIMessage.attachment_filename) and only
used for the Content-Disposition header on download, never as the actual
path on disk.
"""

import os
import uuid

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")


def _ensure_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_file(content: bytes, original_filename: str) -> str:
    """
    Writes `content` to disk and returns the storage-relative path to
    record on the message row.
    """

    _ensure_dir()

    ext = os.path.splitext(original_filename or "")[1][:20]  # cap a malicious "extension"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    full_path = os.path.join(UPLOAD_DIR, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    return stored_name


def read_file(stored_name: str) -> bytes:
    """
    Reads a previously saved file back. Raises FileNotFoundError if the
    stored path is missing (e.g. deleted from disk out-of-band) — callers
    should turn that into a clean 404 rather than a 500.
    """

    # os.path.basename strips any directory components a corrupted/tampered
    # stored path might contain — stored_name should never legitimately
    # have any, this is defense in depth against path traversal.
    full_path = os.path.join(UPLOAD_DIR, os.path.basename(stored_name))

    with open(full_path, "rb") as f:
        return f.read()
