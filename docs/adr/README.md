# Architecture Decision Records (ADRs)

This directory logs significant, hard-to-reverse architectural decisions made while building the **AST-Aware Codebase Oracle**, anchored to [`docs/SPEC.md`](../SPEC.md).

## Index

| ID | Title | Status | Date |
| :--- | :--- | :--- | :--- |
| [ADR-0001](0001-local-bge-embeddings-and-cosine-hnsw.md) | Use Local `BAAI/bge-base-en-v1.5` (768-dim) with Cosine HNSW | Accepted | 2026-11-24 |
| [ADR-0002](0002-latest-commit-incremental-sync-model.md) | Latest-Commit-Per-Repo Incremental Sync via `repo_sync_state` | Accepted | 2026-11-24 |

## Conventions

* **Numbering:** Monotonically increasing 4-digit prefix (`0001-short-kebab-title.md`).
* **Immutability:** Never silently rewrite history—if a decision changes later, mark the old ADR `Superseded by ADR-XXXX` and add a new ADR.
* **Scope:** Record architectural trade-offs (data models, storage engines, ML models, caching/consistency boundaries), not routine code refactors.
