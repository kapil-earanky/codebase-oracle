# ADR-0001: Use Local `BAAI/bge-base-en-v1.5` (768-dim) with Cosine HNSW

* **Status:** Accepted
* **Date:** 2026-11-24
* **Spec References:** [docs/SPEC.md](../SPEC.md) — Section 1 (Model Selection), `FR-2`, `NFR-1.2`, `NFR-2.1`

## Context

`code_chunks.embedding` requires a fixed vector dimension in PostgreSQL (`pgvector`) and a matching HNSW distance operator class. Switching embedding models later requires a full re-index because vectors from different models live in incompatible coordinate spaces.

Our target hardware is an Apple Silicon M4 MacBook Air (24GB unified memory) running Python natively via `uv run` with Metal/MPS acceleration, and our online retrieval SLA (`NFR-1.2`) budgets `< 250 ms` (p95) for query embedding, hybrid retrieval, RRF, and cross-encoder reranking combined.

## Decision

1. **Embedding model:** Use local HuggingFace **`BAAI/bge-base-en-v1.5`** (`768` dimensions, `512`-token maximum context window) running locally on Apple Silicon MPS.
2. **Schema & Index:** Define `code_chunks.embedding` as `vector(768) NOT NULL` and index it with `pgvector` HNSW using **`vector_cosine_ops`** (operator `<=>`).
3. **Normalization & Query Prefix:** Compute unit-normalized embeddings (`normalize_embeddings=True`) and apply the BGE retrieval instruction prefix to queries (not indexed passages).

## Alternatives Considered

* **OpenAI `text-embedding-3-small` (`vector(1536)`):**
  * *Pros:* 8,191-token context window (far fewer oversized AST splits), stronger general semantic baseline, zero local ML memory overhead.
  * *Cons:* Adds ~80–200 ms network RTT to every online query (threatening the `< 250 ms` p95 SLA in `NFR-1.2`), incurs per-token API costs and rate limits during `>= 500 files/min` ingestion (`NFR-2.1`), sends local source code off-machine, and doubles vector storage/HNSW RAM (~600 MB vs. ~300 MB per 100k chunks).
* **Inner Product (`vector_ip_ops`) or L2 (`vector_l2_ops`) HNSW operator classes:**
  * Mathematically equivalent to cosine ordering only when all vectors are strictly unit-normalized. `vector_cosine_ops` is safer against accidental normalization bugs and aligns directly with the `>= 0.95` cosine similarity threshold in Redis Tier-1 semantic caching (`FR-5.1`).

## Consequences

* **Positive:**
  * Zero API cost, offline execution, and ~10–25 ms local query embedding latency on M4 MPS.
  * Half the vector memory/disk footprint compared to 1536-dim embeddings.
  * The strict 512-token ceiling genuinely exercises and validates the recursive sub-AST splitter required by `FR-2`.
* **Negative / Trade-offs:**
  * Large functions/classes will split more frequently than with an 8k-token model, so `FR-2` chunking must use the exact BGE tokenizer to ensure `metadata_header + content` never silently truncates past 512 tokens.
  * Slightly weaker standalone semantic recall than larger cloud models, making hybrid BM25 (`search_vector`) + cross-encoder reranking (`FR-3`, `FR-4`) essential.
