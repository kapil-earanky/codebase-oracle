import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class CodeChunk(BaseModel):
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
    embedding: list[float]

    @field_validator("embedding")
    @classmethod
    def validate_size(cls, v: list[float]) -> list[float]:
        # 768 dim for BAAI/bge-base-en-v1.5
        if len(v) != 768:
            raise ValueError(
                "BAAI/bge-base-en-v1.5 embeddings must have 768 dimensions"
            )
        return v


class Status(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RepoSyncState(BaseModel):
    repo_id: str
    commit_sha: str
    status: Status
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DBHealthStatus(BaseModel):
    healthy: bool
    pgvector_installed: bool
    code_chunks_exists: bool
    error: str | None = None


def compute_chunk_id(
    commit_sha: str, repo_id: str, filepath: str | Path, start_line: int, end_line: int
) -> str:
    delimiter = "||"
    filep = Path(filepath).as_posix()
    combined_string = f"{commit_sha}{delimiter}{repo_id}{delimiter}{filep}{delimiter}{start_line}{delimiter}{end_line}"
    return hashlib.sha256(combined_string.encode("utf-8")).hexdigest()
