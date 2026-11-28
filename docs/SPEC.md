# AST-Aware Codebase Oracle — Engineering Specification & Requirements

An architectural blueprint for a production-grade, AST-aware Retrieval-Augmented Generation (RAG) system optimized for large-scale source code repositories.

---

## 1. Prerequisites & Local Environment Setup

### Target Hardware & OS
* **Primary Workstation:** Apple Silicon M4 MacBook Air with 24GB Unified Memory running macOS.
* **Capacity & Resource Allocation:** The 24GB unified memory configuration comfortably runs local Docker containers alongside local cross-encoder and embedding inference models without memory pressure, while keeping baseline ingestion benchmarks (target $\ge 500\text{ files/minute}$) realistic for an 8-core workstation.

### Local Infrastructure (Docker Compose)
* **Database:** PostgreSQL 16+ container with `pgvector` extension enabled for dense vector similarity indexing (HNSW) and native `tsvector` full-text search.
* **Cache Engine:** Redis 8 / Redis Stack container with RediSearch module enabled for Tier-1 vector similarity lookup and response caching.
* **Observability Stack:** Local OpenTelemetry Collector container backed by Jaeger (distributed tracing) and Prometheus/Grafana (metrics collection) to provide a clear local telemetry destination.

### Source Repository & Git Access
* **Local Git Working Tree:** Ingestion operates on a local `git clone` of a target repository (recommended initial scope: pure Python repository such as `fastapi` or `httpx` to minimize multi-grammar setup overhead on Day 1).
* **Zero Third-Party Dependency:** Ingestion directly parses local `.git` structures and executes `git diff` / `git ls-tree`; no GitHub API/SDK developer key is required.

### API Keys & Model Selection
* **Generation LLM:** Anthropic Claude 3.5 Sonnet (with explicit `cache_control` breakpoints) or Google Gemini 2.5 Flash/Pro for provider-side prompt prefix caching.
* **Embedding Model:** OpenAI `text-embedding-3-small` or local HuggingFace `BAAI/bge-base-en-v1.5`.
* **Reranker Model:** Local `cross-encoder/ms-marco-MiniLM-L-6-v2` executed via `sentence-transformers` or ONNX Runtime to avoid third-party API costs and network latency.

### Python Application Environment
* **Stack Dependencies:** Python 3.11+, `uv` package manager, FastAPI, Pydantic v2, `tree-sitter` + `tree-sitter-python`, `psycopg` + `pgvector`, `redis`, and `opentelemetry-sdk`.

---

## 2. System Overview & Goals

### Purpose
The AST-Aware Codebase Oracle is a high-throughput, low-latency engine designed to ingest, index, and query large source code repositories ($10,000$ to $100,000+$ files). Standard RAG implementations process source code as flat text, creating arbitrary chunk boundaries that split functions, sever context from import blocks, and yield low-relevance retrieval results.

This engine treats code indexing as a distributed systems and compiler-parsing problem. By leveraging Abstract Syntax Tree (AST) parsing, multi-stage hybrid retrieval, semantic/prefix caching, and deterministic evaluation, the system delivers precise, syntactically aware context to Large Language Models (LLMs).

### Why AST-Awareness Matters
Unlike naive character-length splitting—which arbitrarily slices functions mid-statement, strips away module import header scopes, and breaks class inheritance structures—AST parsing segments source files according to language grammar rules. Chunks strictly align with complete logical entities (functions, methods, classes, and attached docstrings) while prepending parent scope signatures, completely eliminating hallucinated function signatures and broken cross-references.

### Why Custom RAG vs. Pointing an LLM at a GitHub Repo
Standard LLM chat web interfaces either rely on outdated training weights or dump raw repository files into the LLM context window. Dumps degrade retrieval accuracy via "lost-in-the-middle" attention degradation, increase API latency, and inflate token costs. By invoking the LLM API directly with explicit `system` and `user` message roles containing only top-5 retrieved AST chunks, and enforcing strict context-grounded prompt rules, we gain total control over provenance, deterministic behavior, and provider-side prompt prefix caching.

### Core Technical Terminology
* **ANN (Approximate Nearest Neighbor):** High-speed vector index traversal (e.g., HNSW in Postgres) that discovers semantically nearest embeddings in logarithmic time rather than brute-force scanning every database row.
* **BM25 / Full-Text Search (FTS):** A probabilistic lexical ranking algorithm (implemented via Postgres `tsvector`/`tsquery`) that scores exact identifier names, error codes, and explicit symbol references.
* **RRF (Reciprocal Rank Fusion):** A rank-aggregation algorithm ($\text{score} = \frac{1}{60 + \text{rank}_{\text{dense}}} + \frac{1}{60 + \text{rank}_{\text{sparse}}}$) that merges dense vector rankings and sparse keyword rankings without requiring raw score normalization.

### Core Learning & Architectural Objectives
* **AST-Based Structural Chunking:** Parse source code according to language grammars, creating context-bound chunks based on logical blocks (functions, methods, classes) rather than raw token/line counts.
* **Hybrid Dense/Sparse Retrieval:** Combine vector similarity (ANN via `pgvector`) with full-text lexical search (BM25 via `tsvector`) using Reciprocal Rank Fusion (RRF).
* **Two-Stage Reranking:** Utilize cross-encoder models to re-score candidate context fragments, ensuring high precision before context assembly.
* **Multi-Tier Caching Architecture:**
  * *Tier 1 (Application Level):* High-efficiency semantic caching using vector similarity over previous query embeddings.
  * *Tier 2 (Provider Level):* Deterministic payload structuring to maximize provider-side prompt prefix caching (Anthropic, OpenAI, Gemini).
* **Deterministic RAG Evaluation:** CI/CD-integrated evaluation framework to compute `Recall@K`, `MRR`, and LLM-as-a-judge faithfulness metrics against a golden dataset.

### Target Tech Stack
* **API & Orchestration:** Python 3.11+ using FastAPI, AsyncIO, and Pydantic v2 (providing strict runtime schema validation, settings management, API contract enforcement, and LLM structured output parsing).
* **AST Parsing Engine:** Tree-sitter (via language-specific bindings).
* **Primary Storage & Retrieval:** PostgreSQL 16+ running in Docker Compose with `pgvector` (HNSW indexing) and native Full-Text Search (`tsvector`/`tsquery` GIN indexing), with a clean migration path to managed AWS RDS Postgres.
* **Semantic Caching:** Redis 8 / Redis Stack running in Docker Compose (RediSearch for ANN vector similarity lookups and key-value payload storage), migration-ready for AWS ElastiCache / MemoryDB.
* **Observability Framework:** OpenTelemetry SDK (distributed tracing, span propagation, metric collection).
* **LLM Integration & Evaluation:** Anthropic Claude 3.5 Sonnet / Google Gemini 2.5 Flash/Pro with explicit system prompt prefix formatting. Tested via FastAPI HTTP/SSE streaming endpoints and a Python CLI evaluation harness.

---

## 3. High-Level Architecture & Data Flows

### Ingestion Pipeline (Offline / Incremental)
```text
[Git Repository] 
       │
       ▼
[Git Walker & Hash Diff] ── (Skip Unchanged Files)
       │
       ▼
[Tree-Sitter AST Parser] ──> Extracts Structural Entities (Class, Function, Struct)
       │
       ▼
[Context Enricher] ────────> Prepends Imports, Module Path, Line Ranges, Parent Scope
       │
       ▼
[Recursive Sub-AST Splitter] > Splits Nodes > Limit (With Overlap Preservation)
       │
       ▼
[Batch Embedding Engine] ──> Computes Dense Embeddings
       │
       ▼
[PostgreSQL Storage] ──────> Atomic Upsert to `pgvector` (HNSW) + `tsvector` (GIN)
```

### Query Execution Path (Online Engine)
```text
Incoming User Query + Target Commit SHA
       │
       ▼
[Query Embedding Generation]
       │
       ▼
[Tier 1: Redis Semantic Cache] ── (Hit: Cosine Sim >= 0.95) ──> Stream Cached Output
       │ (Miss)
       ▼
[Parallel Hybrid Retrieval]
 ├── Dense Vector Search (pgvector HNSW) ──> Top-50 Candidates
 └── Sparse Lexical Search (BM25/FTS)    ──> Top-50 Candidates
       │
       ▼
[Reciprocal Rank Fusion (RRF)] ───────────> Blended Top-25 Candidates
       │
       ▼
[Cross-Encoder Reranker] ────────────────> Top-5 High-Relevance Chunks
       │
       ▼
[Prompt Payload Assembly] ───────────────> Static Prefix (Rules/Tree) + Suffix (Chunks/Query)
       │
       ▼
[Tier 2: Provider Prefix Cache] ─────────> LLM Generation (Streaming SSE)
       │
       ▼
[Async Post-Processing] ──────────────────> Write to Semantic Cache + Emit OTel Spans
```

---

## 4. Functional Requirements (FR)

| Requirement ID | Module | Description & Technical Acceptance Criteria |
| :--- | :--- | :--- |
| **FR-1** | Repository Ingestion | **Incremental Repository Sync:** The system must traverse a local git repository working tree at a target commit SHA, computing SHA-256 content hashes for source files. On subsequent indexing runs, the system must calculate a delta against the previously indexed commit SHA to re-index only added or modified files, while purging deleted file records from storage, using local git commands without external GitHub API requirements. |
| **FR-2** | AST Chunking | **Syntax-Aware Structural Chunking & Comment Preservation:** The system must parse source files using language-specific AST grammars (starting with Python for v1) to extract top-level and nested logical entities (functions, methods, classes, interfaces, structs) alongside their leading docstrings and attached inline/block comments. The system must inject parent scope metadata (file path, module imports, class signature, line numbers) into every chunk. If a single syntax node exceeds the configured embedding model's maximum token budget (e.g., 512 tokens for local BGE or 8,191 tokens for OpenAI embeddings), the system must recursively subdivide the node along child AST boundaries while retaining parent signature headers. |
| **FR-3** | Hybrid Search | **Hybrid Lexical & Semantic Retrieval:** The system must execute parallel semantic vector search and sparse lexical keyword search, scoped strictly by repository ID and commit SHA, and merge the candidate sets into a unified top-25 candidate list using Reciprocal Rank Fusion. |
| **FR-4** | Reranking | **Second-Stage Relevance Reranking:** The system must re-score the top-25 RRF candidates against the user's raw query string using a cross-encoder scoring model, selecting the top-5 highest-scoring context fragments for final prompt assembly. |
| **FR-5.1** | Caching (Tier 1) | **Tier 1 Application Semantic Cache:** The system must store incoming query vector embeddings and generated model responses in an in-memory vector database scoped by commit SHA. On incoming requests, if query vector similarity to a cached query exceeds the configured threshold (default $\ge 0.95$), the system must return the cached response immediately. |
| **FR-5.2** | Caching (Tier 2) | **Tier 2 Provider Prompt Prefix Cache:** The system must structure LLM prompt payloads into a static prefix block (system persona, repository directory tree map, core type definitions) and a dynamic suffix block (retrieved context chunks and user query) to maximize provider-side prompt prefix caching. |
| **FR-6** | Generation & Citations | **Grounded Streaming Generation & Citations:** The system must stream response text via Server-Sent Events (SSE). Prompt instructions must require inline citations in the exact format `path/to/file.ext:Lstart-Lend` for all code assertions, and force an explicit fallback message when retrieved context is insufficient. |
| **FR-7** | Evaluation | **Deterministic Evaluation Harness:** The system must provide a CLI evaluation runner that executes automated test suites over a golden evaluation dataset ($\ge 20$ query, ground-truth chunk, expected output triplets), computing retrieval metrics (`Recall@5`, `MRR`) and response quality scores. |

---

## 5. Non-Functional Requirements (NFR)

| Metric ID | Parameter | Performance Target / Constraint | Measurement Methodology |
| :--- | :--- | :--- | :--- |
| **NFR-1.1** | Latency | Semantic Cache Hit (p95) **$< 20\text{ ms}$** | OTel span duration for Redis lookup and validation. |
| **NFR-1.2** | Latency | Hybrid Retrieval + Reranking (p95) **$< 250\text{ ms}$** | Total pipeline latency prior to initial LLM token generation. |
| **NFR-1.3** | Latency | Time-To-First-Token (TTFT) | $\ge 50\%$ reduction on Provider Prefix Cache hit vs. cold generation. |
| **NFR-2.1** | Throughput | Ingestion Speed **$\ge 500\text{ files/minute}$** | Benchmarked locally on target M4 MacBook Air (24GB RAM). |
| **NFR-2.2** | Integrity | Strict Ingestion Idempotency & Data Integrity | Re-indexing an already-indexed commit SHA must yield 0 duplicate database entries, produce unchanged total row counts, and output identical retrieval result sets. |
| **NFR-3** | Cost & Efficiency | Token Expenditure Reduction | System must yield a $\ge 60\%$ reduction in token expenses across multi-turn sessions using multi-tier caching. |
| **NFR-4** | Observability | Observability & Metrics Export | $100\%$ instrumentation across ingestion, vector retrieval, reranking, and generation modules exporting OTLP traces and metrics to local Jaeger/Prometheus backends. |
| **NFR-5** | Resilience | Graceful Fallback & Retry Logic | Circuit breaker bypass on Redis failure; exponential backoff with jitter on HTTP 429/5xx status codes from LLM providers. |
| **NFR-6 (P1)** | Context Precision | Anti-"Lost-in-the-Middle" Gain | $\ge 20\%$ improvement in answer accuracy / faithfulness and $\ge 75\%$ reduction in input token payload size compared to a naive full-file / raw-context baseline. |

---

## 6. High-Level Data Schemas & Interfaces

### Code Chunk Entity (`CodeChunk`)
* `chunk_id` *(String / Primary Key)*: Unique deterministic hash: `sha256(commit_sha:file_path:start_line:end_line)`.
* `repo_id` *(String)*: Unique identifier for the repository.
* `commit_sha` *(String)*: Git commit hash associated with this index entry.
* `file_path` *(String)*: Relative path of the source file within the repository.
* `language` *(String)*: Programming language identified via file extension and parser grammar.
* `symbol_name` *(String, Optional)*: Name of the top-level symbol (e.g., function or class name).
* `symbol_type` *(String)*: Node type classified by AST (e.g., `function_definition`, `class_declaration`).
* `start_line` / `end_line` *(Integer)*: 1-based line bounds of the chunk within the source file.
* `content` *(String)*: Extracted raw source code fragment.
* `metadata_header` *(String)*: Contextual header injected at the top of the chunk (includes imports, file location, and parent signatures).
* `embedding` *(Vector)*: Dense vector embedding representation (e.g., 768-dim or 1536-dim).
* `tsvector` *(Search Vector)*: Full-text search tokens generated for PostgreSQL BM25/FTS execution.

### Semantic Cache Entry (`CacheEntry`)
* `cache_key` *(String)*: Redis entry identifier.
* `commit_sha` *(String)*: Git commit SHA scope key.
* `query_text` *(String)*: Original incoming natural language query string.
* `query_embedding` *(Vector)*: Dense vector embedding of the input query.
* `response_text` *(String)*: Generated model response payload.
* `cited_chunks` *(List of Strings)*: List of `chunk_id` references supporting the response.
* `created_at` *(Timestamp)*: Cache record creation timestamp.

---

## 7. Execution Roadmap & 7-Day Implementation Plan

### Milestone Schedule
```text
[Day 1-2] Milestone 1: Prerequisites, Docker Setup & Ingestion Engine
  ├── Launch local Docker Compose stack (Postgres 16+ with pgvector, Redis, OTel/Jaeger)
  ├── Build Tree-sitter AST parser for Python working tree with comment/docstring extraction
  └── Implement git diff walker for incremental sync without GitHub API dependencies

[Day 3-4] Milestone 2: Hybrid Retrieval & SSE Streaming API
  ├── Build parallel pgvector (ANN) + tsvector (BM25) search with RRF blending
  ├── Integrate local cross-encoder model for top-5 candidate reranking
  └── Expose FastAPI streaming SSE endpoint with mandatory code location citations

[Day 5] Milestone 3: Two-Tier Caching & Telemetry Pipeline
  ├── Implement Redis vector similarity semantic cache (Tier 1, threshold >= 0.95)
  ├── Structure prompt payloads with static prefixes for Claude/Gemini caching (Tier 2)
  └── Export OpenTelemetry spans and metrics to local Jaeger and Prometheus services

[Day 6-7] Milestone 4: Evaluation Harness & Benchmarking
  ├── Curate Golden Evaluation Dataset (>= 20 triplets)
  ├── Build Python CLI harness computing Recall@5, MRR, and LLM-as-a-judge scores
  └── Conduct ablation study (Naive Chunking vs. AST + RRF + Reranking)
```