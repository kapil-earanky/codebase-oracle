from pathlib import Path

from pydantic import BaseModel

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
}


class GitException(RuntimeError):
    """Raised when a local git plumbing command fails or returns invalid data."""


class NonUtf8FileError(GitException):
    """Raised when a tracked file cannot be decoded as UTF-8 text."""


class SourceFile(BaseModel):
    """Exact committed snapshot of a single source file."""

    file_path: str
    language: str
    content: str
    content_sha256: str


class RepoDelta(BaseModel):
    """Incremental file change set between prev_commit_sha and target commit_sha."""

    commit_sha: str
    prev_commit_sha: str | None = None
    is_full_sync: bool
    files_to_index: list[str]
    files_to_delete: list[str]


def detect_language(
    file_path: str | Path,
    extension_map: dict[str, str] | None = None,
) -> str | None:
    """Return the canonical language name for a file path, or None if unsupported."""
    mapping = EXTENSION_TO_LANGUAGE if extension_map is None else extension_map
    return mapping.get(Path(file_path).suffix.lower())
