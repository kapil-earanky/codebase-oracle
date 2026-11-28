-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_chunks (
    chunk_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL, -- Unique identifier for the repository.
    commit_sha TEXT NOT NULL, -- Git commit hash associated with this index entry.
    file_path TEXT NOT NULL, -- Relative path of the source file within the repository.
    language TEXT NOT NULL, -- Programming language identified via file extension and parser grammar.
    symbol_name TEXT, -- Name of the top-level symbol (e.g., function or class name).
    symbol_type TEXT NOT NULL, -- Node type classified by AST (e.g., function_definition, class_declaration).
    start_line INT NOT NULL CHECK (start_line >= 1), -- 1-based line bounds of the chunk within the source file.
    end_line INT NOT NULL CHECK (end_line >= start_line), -- 1-based line bounds of the chunk within the source file.
    content TEXT NOT NULL, -- Extracted raw source code fragment.
    metadata_header TEXT NOT NULL, -- Contextual header injected at the top of the chunk (includes imports, file location, and parent signatures).
    embedding vector(768) NOT NULL, -- Dense vector embedding representation - 768 dim for BAAI/bge-base-en-v1.5
    search_vector tsvector NOT NULL, -- Full-text search tokens generated for PostgreSQL BM25/FTS execution.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS code_chunks_embedding_idx on code_chunks using HNSW (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS code_chunks_search_vector_idx ON code_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS code_chunks_repo_id_commit_sha_file_path_idx ON code_chunks (repo_id, commit_sha, file_path);

CREATE TABLE IF NOT EXISTS repo_sync_state (
    repo_id TEXT PRIMARY KEY,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);