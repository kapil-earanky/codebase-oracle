import asyncio
import hashlib
import logging
from pathlib import Path

from app.ingestion.models import (
    EXTENSION_TO_LANGUAGE,
    GitException,
    NonUtf8FileError,
    RepoDelta,
    SourceFile,
    detect_language,
)

logger = logging.getLogger(__name__)


async def _run_git(repo_path: Path, *args: str) -> bytes:
    """Run a local git command asynchronously and return raw stdout bytes."""
    if not repo_path.is_dir():
        raise GitException(f"Repository path does not exist or is not a directory: {repo_path}")

    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=repo_path.as_posix(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace").strip()
        raise GitException(f"git {' '.join(args)} failed (exit {process.returncode}): {err_msg}")

    return stdout


async def get_commit_sha(repo_path: Path, ref: str = "HEAD") -> str:
    """Resolve a ref (branch, tag, short SHA, HEAD) to a full 40-char commit SHA."""
    if not ref or ref.startswith("-"):
        raise GitException(f"Invalid git ref: {ref!r}")

    raw = await _run_git(repo_path, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return raw.decode("utf-8").strip()


async def commit_exists(repo_path: Path, commit_sha: str) -> bool:
    """Return True if commit_sha exists as a commit object in the local repository."""
    if not commit_sha or commit_sha.startswith("-"):
        return False

    try:
        await _run_git(repo_path, "cat-file", "-e", f"{commit_sha}^{{commit}}")
        return True
    except GitException:
        return False


async def list_tracked_files(
    repo_path: Path,
    commit_sha: str,
    extension_map: dict[str, str] | None = None,
) -> list[str]:
    """List all supported tracked source files at commit_sha in sorted POSIX order."""
    raw = await _run_git(repo_path, "ls-tree", "-r", "-z", "--name-only", commit_sha)
    if not raw:
        return []

    tokens = raw.split(b"\x00")
    if tokens and tokens[-1] == b"":
        tokens.pop()

    files = [
        path
        for token in tokens
        if detect_language(path := token.decode("utf-8"), extension_map) is not None
    ]
    return sorted(files)


def _parse_name_status_z(
    raw: bytes,
    extension_map: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Parse `git diff --name-status -z` output into (files_to_index, files_to_delete).

    Git formats `-z` records as NUL-terminated tokens:
      - A/M/T/D:  <status>\\0<path>\\0
      - R*/C*:    <status>\\0<old_path>\\0<new_path>\\0
    """
    if not raw:
        return [], []

    tokens = raw.split(b"\x00")
    if tokens and tokens[-1] == b"":
        tokens.pop()

    to_index: set[str] = set()
    to_delete: set[str] = set()

    i = 0
    n = len(tokens)
    while i < n:
        status = tokens[i].decode("utf-8")

        if status.startswith(("R", "C")):
            if i + 2 >= n:
                raise GitException(f"Malformed git diff -z rename/copy record at token {i}: {status!r}")
            old_path = tokens[i + 1].decode("utf-8")
            new_path = tokens[i + 2].decode("utf-8")
            i += 3

            if status.startswith("R") and detect_language(old_path, extension_map) is not None:
                to_delete.add(old_path)
            if detect_language(new_path, extension_map) is not None:
                to_index.add(new_path)
        else:
            if i + 1 >= n:
                raise GitException(f"Malformed git diff -z record at token {i}: {status!r}")
            path = tokens[i + 1].decode("utf-8")
            i += 2

            if detect_language(path, extension_map) is None:
                continue

            code = status[0]
            if code == "A":
                to_index.add(path)
            elif code == "D":
                to_delete.add(path)
            elif code in ("M", "T"):
                to_delete.add(path)
                to_index.add(path)
            else:
                logger.warning("Ignoring unhandled git diff status %r for %s", status, path)

    return sorted(to_index), sorted(to_delete)


async def compute_delta(
    repo_path: Path,
    target_commit_sha: str,
    prev_commit_sha: str | None = None,
    extension_map: dict[str, str] | None = None,
) -> RepoDelta:
    """Compute files to delete and index when syncing from prev_commit_sha to target_commit_sha.

    Per ADR-0002:
      - Cold start (prev_commit_sha is None) -> full sync via `git ls-tree`.
      - Same commit -> empty no-op delta.
      - Unreachable prev_commit_sha (e.g., rebase/force-push) -> fallback to full sync.
      - Otherwise -> incremental delta via `git diff --name-status -z <prev> <target>`.
    """
    resolved_target = await get_commit_sha(repo_path, target_commit_sha)

    if prev_commit_sha is None:
        files = await list_tracked_files(repo_path, resolved_target, extension_map)
        return RepoDelta(
            commit_sha=resolved_target,
            prev_commit_sha=None,
            is_full_sync=True,
            files_to_index=files,
            files_to_delete=[],
        )

    if prev_commit_sha == resolved_target:
        return RepoDelta(
            commit_sha=resolved_target,
            prev_commit_sha=prev_commit_sha,
            is_full_sync=False,
            files_to_index=[],
            files_to_delete=[],
        )

    if not await commit_exists(repo_path, prev_commit_sha):
        logger.warning(
            "Previous commit %s not found in %s; falling back to full sync",
            prev_commit_sha,
            repo_path,
        )
        files = await list_tracked_files(repo_path, resolved_target, extension_map)
        return RepoDelta(
            commit_sha=resolved_target,
            prev_commit_sha=prev_commit_sha,
            is_full_sync=True,
            files_to_index=files,
            files_to_delete=[],
        )

    raw_diff = await _run_git(
        repo_path,
        "diff",
        "--name-status",
        "-z",
        prev_commit_sha,
        resolved_target,
    )
    files_to_index, files_to_delete = _parse_name_status_z(raw_diff, extension_map)
    return RepoDelta(
        commit_sha=resolved_target,
        prev_commit_sha=prev_commit_sha,
        is_full_sync=False,
        files_to_index=files_to_index,
        files_to_delete=files_to_delete,
    )


async def read_file_at_commit(
    repo_path: Path,
    commit_sha: str,
    file_path: str | Path,
    extension_map: dict[str, str] | None = None,
) -> SourceFile:
    """Read exact committed bytes of file_path at commit_sha (preserving leading lines/whitespace)."""
    posix_path = Path(file_path).as_posix()
    language = detect_language(posix_path, extension_map)
    if language is None:
        supported = ", ".join(sorted((extension_map or EXTENSION_TO_LANGUAGE).keys()))
        raise GitException(f"Unsupported file extension for {posix_path!r} (supported: {supported})")

    raw = await _run_git(repo_path, "show", f"{commit_sha}:{posix_path}")
    content_sha256 = hashlib.sha256(raw).hexdigest()

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NonUtf8FileError(f"File {posix_path!r} at {commit_sha} is not valid UTF-8") from exc

    return SourceFile(
        file_path=posix_path,
        language=language,
        content=content,
        content_sha256=content_sha256,
    )


async def read_files_at_commit(
    repo_path: Path,
    commit_sha: str,
    file_paths: list[str],
    max_concurrency: int = 16,
    extension_map: dict[str, str] | None = None,
) -> list[SourceFile]:
    """Read multiple files at commit_sha with bounded concurrency, skipping non-UTF-8 files."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _read_one(path: str) -> SourceFile | None:
        async with semaphore:
            try:
                return await read_file_at_commit(repo_path, commit_sha, path, extension_map)
            except NonUtf8FileError:
                logger.warning("Skipping non-UTF-8 file %s at %s", path, commit_sha)
                return None

    results = await asyncio.gather(*(_read_one(path) for path in file_paths))
    return [sf for sf in results if sf is not None]
