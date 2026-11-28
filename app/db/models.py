import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5 (see ADR-0001)


class CodeChunk(BaseModel):
    """AST-derived source code chunk prior to vector embedding."""

    chunk_id: str
    repo_id: str
    commit_sha: str
    file_path: str
    language: str
    symbol_name: str | None = None
    symbol_type: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str
    metadata_header: str
    search_vector: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def check_end_ge_start(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class EmbeddedCodeChunk(CodeChunk):
    """AST code chunk paired with its dense embedding vector for PostgreSQL storage."""

    embedding: list[float]

    @field_validator("embedding")
    @classmethod
    def validate_size(cls, v: list[float]) -> list[float]:
        if len(v) != EMBEDDING_DIM:
            raise ValueError(
                f"BAAI/bge-base-en-v1.5 embeddings must have {EMBEDDING_DIM} dimensions"
            )
        return v


class Status(StrEnum):
    """Lifecycle status of a repository synchronization run."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RepoSyncState(BaseModel):
    """Active synced commit pointer per repository (see ADR-0002)."""

    repo_id: str
    commit_sha: str
    status: Status
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DBHealthStatus(BaseModel):
    """Structured readiness probe result for PostgreSQL and pgvector."""

    healthy: bool
    pgvector_installed: bool
    code_chunks_exists: bool
    error: str | None = None


def compute_chunk_id(
    commit_sha: str,
    repo_id: str,
    filepath: str | Path,
    start_line: int,
    end_line: int,
) -> str:
    """Compute a deterministic SHA-256 primary key for a code chunk."""
    posix_path = Path(filepath).as_posix()
    payload = f"{commit_sha}||{repo_id}||{posix_path}||{start_line}||{end_line}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
