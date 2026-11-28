from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.models import (
    CodeChunk,
    DBHealthStatus,
    EmbeddedCodeChunk,
    RepoSyncState,
    Status,
    compute_chunk_id,
)


def _chunk_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "repo_id": "codebase-oracle",
        "commit_sha": "abc123def456",
        "file_path": "app/db/models.py",
        "language": "python",
        "symbol_name": "compute_chunk_id",
        "symbol_type": "function_definition",
        "start_line": 1,
        "end_line": 10,
        "content": "def compute_chunk_id(): ...",
        "metadata_header": "# file: app/db/models.py",
    }
    base.update(overrides)
    if "chunk_id" not in base:
        base["chunk_id"] = compute_chunk_id(
            commit_sha=base["commit_sha"],
            repo_id=base["repo_id"],
            filepath=base["file_path"],
            start_line=base["start_line"],
            end_line=base["end_line"],
        )
    return base


def test_code_chunk_valid_and_optional_defaults() -> None:
    chunk = CodeChunk(**_chunk_kwargs(symbol_name=None))

    assert chunk.symbol_name is None
    assert chunk.search_vector is None
    assert chunk.created_at.tzinfo is not None
    assert chunk.start_line == 1
    assert chunk.end_line == 10


def test_code_chunk_single_line_allowed() -> None:
    chunk = CodeChunk(**_chunk_kwargs(start_line=5, end_line=5))

    assert chunk.start_line == 5
    assert chunk.end_line == 5


@pytest.mark.parametrize(
    ("start_line", "end_line"),
    [
        (0, 1),
        (-3, 5),
        (1, 0),
        (10, 5),
    ],
)
def test_code_chunk_invalid_line_bounds(start_line: int, end_line: int) -> None:
    with pytest.raises(ValidationError):
        CodeChunk(
            **_chunk_kwargs(
                chunk_id="dummy-id",
                start_line=start_line,
                end_line=end_line,
            )
        )


def test_embedded_code_chunk_valid_768_dim() -> None:
    embedding = [0.01] * 768
    chunk = EmbeddedCodeChunk(**_chunk_kwargs(), embedding=embedding)

    assert len(chunk.embedding) == 768


@pytest.mark.parametrize("dim", [0, 767, 769, 1536])
def test_embedded_code_chunk_rejects_wrong_dimension(dim: int) -> None:
    with pytest.raises(ValidationError, match="768 dimensions"):
        EmbeddedCodeChunk(**_chunk_kwargs(), embedding=[0.0] * dim)


def test_repo_sync_state_status_enum() -> None:
    state = RepoSyncState(
        repo_id="codebase-oracle",
        commit_sha="abc123",
        status="completed",  # type: ignore[arg-type]
    )

    assert state.status is Status.COMPLETED
    assert state.status == "completed"
    assert state.last_updated_at.tzinfo is not None

    with pytest.raises(ValidationError):
        RepoSyncState(
            repo_id="codebase-oracle",
            commit_sha="abc123",
            status="unknown_status",  # type: ignore[arg-type]
        )


def test_db_health_status_defaults() -> None:
    status = DBHealthStatus(
        healthy=True,
        pgvector_installed=True,
        code_chunks_exists=True,
    )

    assert status.error is None


def test_compute_chunk_id_deterministic_and_path_normalized() -> None:
    id_from_str = compute_chunk_id("sha1", "repo-a", "app/db/models.py", 1, 10)
    id_from_path = compute_chunk_id("sha1", "repo-a", Path("app/db/models.py"), 1, 10)

    assert id_from_str == id_from_path
    assert len(id_from_str) == 64


def test_compute_chunk_id_changes_on_any_input_change() -> None:
    base = compute_chunk_id("sha1", "repo-a", "app/main.py", 1, 10)

    assert base != compute_chunk_id("sha2", "repo-a", "app/main.py", 1, 10)
    assert base != compute_chunk_id("sha1", "repo-b", "app/main.py", 1, 10)
    assert base != compute_chunk_id("sha1", "repo-a", "app/other.py", 1, 10)
    assert base != compute_chunk_id("sha1", "repo-a", "app/main.py", 2, 10)
    assert base != compute_chunk_id("sha1", "repo-a", "app/main.py", 1, 11)
