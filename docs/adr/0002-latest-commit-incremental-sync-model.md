# ADR-0002: Latest-Commit-Per-Repo Incremental Sync via `repo_sync_state`

* **Status:** Accepted
* **Date:** 2026-11-24
* **Spec References:** [docs/SPEC.md](../SPEC.md) — `FR-1`, `FR-3`, `NFR-1.2`, `NFR-2.2`, Section 6 (`CodeChunk`)

## Context

Incremental repository ingestion (`FR-1`) must re-index only added or modified files and purge deleted files when advancing a repository from previously indexed commit `A` to target commit `B`, without re-embedding unchanged files.

Simultaneously, online hybrid retrieval (`FR-3`) scopes every query by `(repo_id, commit_sha)`. If an incremental sync only writes chunks for the few modified files under `commit_sha = 'B'` while leaving unchanged files tagged with `commit_sha = 'A'`, queries filtering `WHERE repo_id = %s AND commit_sha = 'B'` will miss all unchanged files.

## Decision

Adopt a **Simpler v1 — Latest-Commit-Per-Repo** storage and sync model:

1. **Single sync-state table (`repo_sync_state`):** Track the active synced `commit_sha` per `repo_id` (dropping per-file `file_sync_state` for v1).
2. **Git-native delta calculation:** Rely on local Git (`git diff --name-status <prev_commit_sha> <target_commit_sha>`) to identify Added (`A`), Modified (`M`), Deleted (`D`), and Renamed (`R`) files rather than maintaining a parallel per-file SHA-256 hash table in Postgres.
3. **Atomic commit advancement on `code_chunks`:** Within a transaction when advancing `prev_commit_sha -> target_commit_sha`:
   * Delete chunks belonging to deleted, modified, and old-path renamed files (scoped by `(repo_id, prev_commit_sha, file_path)` to utilize the composite B-tree index).
   * Insert newly parsed/embedded chunks for added, modified, and new-path renamed files with `commit_sha = target_commit_sha`.
   * Advance `commit_sha` on unchanged chunks from `prev_commit_sha` to `target_commit_sha`.
   * Update `repo_sync_state` to `target_commit_sha`.

## Alternatives Considered

* **Resilient v1 (`repo_sync_state` + `file_sync_state` with per-file SHA-256 hashes):**
  * *Pros:* Supports crash-resumable batched ingestion for huge initial loads, provides a content-hash fallback when `prev_commit_sha` is unreachable after a rebase/force-push, and avoids re-embedding pure renames or reverts.
  * *Cons:* Extra table, extra write amplification and reconciliation logic during v1 bring-up.
* **True Multi-Commit Content-Addressed Model (`code_chunks` keyed by `file_sha` + `commit_files(repo_id, commit_sha, file_path, file_sha)`):**
  * *Pros:* Zero `UPDATE`s on unchanged chunks across commits and ability to query multiple historical commits concurrently.
  * *Cons:* Forces a `JOIN` between `code_chunks` and `commit_files` on every online hybrid query, complicating PostgreSQL's planner and `pgvector` HNSW filtered index scans (`NFR-1.2`).

## Consequences

* **Positive:**
  * Minimal schema surface area (`code_chunks` + `repo_sync_state`).
  * Online retrieval (`FR-3`) remains a fast, single-table query on `code_chunks` filtered by `(repo_id, commit_sha)`, preserving clean HNSW index execution.
  * Clean rollback semantics on incremental runs: if a sync fails before committing `repo_sync_state`, the database remains cleanly at `prev_commit_sha`.
* **Negative / Accepted v1 Trade-offs:**
  * Only one active `commit_sha` per `repo_id` is queryable at a time (no simultaneous multi-branch/historical commit querying).
  * If a large initial cold ingest crashes mid-way, it restarts from scratch rather than resuming per-file checkpoints.
  * If local Git history is rebased/force-pushed such that `prev_commit_sha` is no longer reachable, ingestion must fall back to a full repo re-index.
  * **Implementation note for `chunk_id`:** Because unchanged rows advance their `commit_sha` in place, `chunk_id` stability across commits (for `NFR-2.2` idempotency and Redis `cited_chunks` references) must be handled deliberately—either keeping original `chunk_id` on untouched rows or keying `chunk_id` on `(repo_id, file_path, start_line, end_line, content_hash)` rather than mutating primary keys on every commit.
  * **Spec alignment:** Revisit `FR-1` in [docs/SPEC.md](../SPEC.md) if we keep per-file SHA-256 hashing out of the database permanently, or supersede this ADR if we introduce `file_sync_state` for massive repo benchmarks later.
