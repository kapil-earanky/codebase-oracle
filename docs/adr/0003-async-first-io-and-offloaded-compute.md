# ADR-0003: Async-First I/O (`psycopg` v3 `AsyncConnectionPool`) with Offloaded Compute

* **Status:** Accepted
* **Date:** 2026-11-24
* **Spec References:** [docs/SPEC.md](../SPEC.md) — `FR-3`, `FR-4`, `FR-6`, `NFR-1.2`, `NFR-2.1`; [.gemini/styleguide.md](../../.gemini/styleguide.md)

## Context

The Codebase Oracle has two workloads:
1. **Online Query Engine (FastAPI):** High concurrency, parallel database queries (`pgvector` HNSW + PostgreSQL `tsvector` FTS via `asyncio.gather`), Redis semantic cache lookups, and Server-Sent Events (SSE) LLM streaming.
2. **Offline Ingestion Engine (CLI):** Local Git commands, Tree-sitter AST parsing, batched local BGE embeddings on Apple Silicon MPS, and bulk PostgreSQL upserts.

Maintaining separate synchronous and asynchronous database access layers duplicates connection management, type registration (`pgvector`), and repository queries.

## Decision

Standardize on an **async-first I/O architecture** across the codebase:

1. **Unified async DB pool:** Use `psycopg` (v3) with `psycopg_pool.AsyncConnectionPool` (constructed with `open=False` and explicitly opened/closed via FastAPI `lifespan` or an async CLI context manager) and `configure=register_vector_async` so every pooled connection natively supports `vector(768)`.
2. **Async network & cache clients:** Use `redis.asyncio` and async LLM/HTTP clients (`httpx` / provider async SDKs) for non-blocking Tier-1 cache lookups, parallel hybrid retrieval, and SSE streaming.
3. **Explicit compute offloading:** Never run synchronous CPU-bound or MPS inference work directly on the `asyncio` event loop. Offload Tree-sitter parsing, local BGE embedding (`BAAI/bge-base-en-v1.5`), and cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`) using `asyncio.to_thread` (online requests) or worker pools (bulk offline ingestion).

## Alternatives Considered

* **Sync `ConnectionPool` for ingestion + `AsyncConnectionPool` for FastAPI:**
  * *Pros:* Simpler mental model for CLI scripts.
  * *Cons:* Splits the data-access layer in two (duplicate queries, pool setup, and tests).
* **Fully synchronous FastAPI (`def` endpoints using Starlette's threadpool):**
  * *Pros:* Avoids accidental event-loop blocking.
  * *Cons:* Makes true parallel dense + sparse fan-out (`FR-3`), Redis circuit-breaker timeouts (`NFR-5`), and async SSE token streaming (`FR-6`) clunkier and harder to instrument cleanly with OpenTelemetry context propagation.

## Consequences

* **Positive:**
  * Single shared PostgreSQL repository and pooling layer across CLI ingestion, online API, and evaluation harness.
  * Natural parallel execution (`asyncio.gather`) for dense + sparse retrieval (`FR-3`) and non-blocking SSE streaming (`FR-6`).
* **Negative / Discipline Required:**
  * Requires strict discipline to avoid calling synchronous blocking libraries (e.g., `subprocess.run`, `sentence_transformers.encode`, `tree_sitter.Parser.parse`) directly inside `async def` routes without offloading.
  * Async tests require `pytest-asyncio` (or `anyio`) in dev dependencies.
