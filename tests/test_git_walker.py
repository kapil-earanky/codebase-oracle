import hashlib
import subprocess
from pathlib import Path

import pytest

from app.ingestion.git_walker import (
    commit_exists,
    compute_delta,
    get_commit_sha,
    list_tracked_files,
    read_file_at_commit,
    read_files_at_commit,
)
from app.ingestion.models import GitException, NonUtf8FileError


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a fresh, self-contained local Git repository with an initial commit."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "src").mkdir()
    (repo / "src" / "alpha.py").write_text("\n\ndef alpha() -> int:\n    return 1\n", encoding="utf-8")
    (repo / "src" / "beta.py").write_text("def beta() -> int:\n    return 2\n", encoding="utf-8")
    (repo / "README.md").write_text("# Sample Repo\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial commit")
    return repo


async def test_get_commit_sha_and_invalid_refs(git_repo: Path) -> None:
    sha = await get_commit_sha(git_repo, "HEAD")
    assert len(sha) == 40
    assert await commit_exists(git_repo, sha) is True
    assert await commit_exists(git_repo, "0" * 40) is False

    with pytest.raises(GitException):
        await get_commit_sha(git_repo, "--all")

    with pytest.raises(GitException):
        await get_commit_sha(git_repo, "nonexistent-ref")


async def test_compute_delta_cold_start_filters_supported_languages(git_repo: Path) -> None:
    head = await get_commit_sha(git_repo)
    delta = await compute_delta(git_repo, target_commit_sha=head, prev_commit_sha=None)

    assert delta.commit_sha == head
    assert delta.prev_commit_sha is None
    assert delta.is_full_sync is True
    assert delta.files_to_index == ["src/alpha.py", "src/beta.py"]
    assert delta.files_to_delete == []


async def test_compute_delta_same_commit_is_noop(git_repo: Path) -> None:
    head = await get_commit_sha(git_repo)
    delta = await compute_delta(git_repo, target_commit_sha=head, prev_commit_sha=head)

    assert delta.is_full_sync is False
    assert delta.files_to_index == []
    assert delta.files_to_delete == []


async def test_compute_delta_incremental_add_modify_delete_rename_and_spaces(
    git_repo: Path,
) -> None:
    commit_a = await get_commit_sha(git_repo)

    # Modify alpha.py
    (git_repo / "src" / "alpha.py").write_text("def alpha() -> int:\n    return 42\n", encoding="utf-8")
    # Rename beta.py -> renamed file.py (with space!)
    _git(git_repo, "mv", "src/beta.py", "src/renamed file.py")
    # Add gamma.py and an unsupported file
    (git_repo / "src" / "gamma.py").write_text("x = 1\n", encoding="utf-8")
    (git_repo / "notes.txt").write_text("ignored\n", encoding="utf-8")
    # Add a file to delete in next commit
    (git_repo / "src" / "temp.py").write_text("temp = True\n", encoding="utf-8")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "second commit")
    commit_b = await get_commit_sha(git_repo)

    delta_ab = await compute_delta(git_repo, target_commit_sha=commit_b, prev_commit_sha=commit_a)
    assert delta_ab.is_full_sync is False
    assert delta_ab.files_to_index == [
        "src/alpha.py",
        "src/gamma.py",
        "src/renamed file.py",
        "src/temp.py",
    ]
    assert delta_ab.files_to_delete == ["src/alpha.py", "src/beta.py"]

    # Delete temp.py and rename notes.txt -> converted.py + gamma.py -> archived.txt
    _git(git_repo, "rm", "src/temp.py")
    _git(git_repo, "mv", "notes.txt", "converted.py")
    _git(git_repo, "mv", "src/gamma.py", "archived.txt")
    _git(git_repo, "commit", "-m", "third commit")
    commit_c = await get_commit_sha(git_repo)

    delta_bc = await compute_delta(git_repo, target_commit_sha=commit_c, prev_commit_sha=commit_b)
    assert delta_bc.is_full_sync is False
    assert delta_bc.files_to_index == ["converted.py"]
    assert delta_bc.files_to_delete == ["src/gamma.py", "src/temp.py"]


async def test_compute_delta_unreachable_prev_falls_back_to_full_sync(git_repo: Path) -> None:
    head = await get_commit_sha(git_repo)
    fake_rebased_sha = "a" * 40

    delta = await compute_delta(git_repo, target_commit_sha=head, prev_commit_sha=fake_rebased_sha)
    assert delta.is_full_sync is True
    assert delta.prev_commit_sha == fake_rebased_sha
    assert delta.files_to_index == ["src/alpha.py", "src/beta.py"]
    assert delta.files_to_delete == []


async def test_read_file_at_commit_preserves_leading_lines_and_ignores_dirty_tree(
    git_repo: Path,
) -> None:
    commit_a = await get_commit_sha(git_repo)
    expected_content = "\n\ndef alpha() -> int:\n    return 1\n"

    # Dirty the working tree without committing — reader must still see commit_a
    (git_repo / "src" / "alpha.py").write_text("DIRTY UNCOMMITTED EDIT\n", encoding="utf-8")

    sf = await read_file_at_commit(git_repo, commit_a, "src/alpha.py")
    assert sf.file_path == "src/alpha.py"
    assert sf.language == "python"
    assert sf.content == expected_content
    assert sf.content_sha256 == hashlib.sha256(expected_content.encode("utf-8")).hexdigest()


async def test_read_files_at_commit_skips_non_utf8_files(git_repo: Path) -> None:
    (git_repo / "src" / "binary.py").write_bytes(b"\x80\x81\xfe\xff")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add invalid utf8 py file")
    head = await get_commit_sha(git_repo)

    with pytest.raises(NonUtf8FileError):
        await read_file_at_commit(git_repo, head, "src/binary.py")

    tracked = await list_tracked_files(git_repo, head)
    assert "src/binary.py" in tracked

    files = await read_files_at_commit(git_repo, head, tracked)
    paths = sorted(f.file_path for f in files)
    assert paths == ["src/alpha.py", "src/beta.py"]
