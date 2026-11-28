Gemini / Antigravity Workspace Style & Review Rules

Follow all guidelines defined in AGENTS.md at the repository root and validate changes against docs/SPEC.md.

Code Review Focus Areas

Socratic Guidance First: When reviewing PRs or uncommitted diffs in VS Code, identify bugs, race conditions, latency bottlenecks, or spec violations and ask targeted questions or propose high-level design fixes rather than dumping complete code rewrites.

Python & FastAPI Idioms:

Enforce Pydantic v2 (BaseModel, BaseSettings, Field) for configuration and API payloads.

Ensure CPU-bound work (Tree-sitter parsing, local cross-encoder inference) does not block async def FastAPI routes (offload via asyncio.to_thread or process pools).

Verify all SQL queries against code_chunks are parameterized (psycopg %s placeholders) and filter by (repo_id, commit_sha).

Performance & SLA Awareness:

Keep Tier-1 semantic cache lookups < 20 ms (p95) and hybrid retrieval + reranking < 250 ms (p95).

Verify OpenTelemetry spans wrap every major pipeline stage (embedding, Redis lookup, vector search, FTS search, reranking, LLM TTFT).