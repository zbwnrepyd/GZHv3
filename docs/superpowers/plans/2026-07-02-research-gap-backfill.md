# Research Gap Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable post-research backfill script that improves visible card field completeness without fabricating private metrics.

**Architecture:** Add a focused CLI under `scripts/` that reads the RenderContract, detects missing visible fields, and fills only safe sources: existing `market_estimates` rows and local industry benchmark defaults. It writes through SQLite tables already used by the renderer, preserving status semantics (`proxy`, `industry_avg`, `unavailable`).

**Tech Stack:** Python standard library, SQLite, existing `RenderAssembler`, existing `industry_benchmarks`.

---

### Task 1: Backfill Script

**Files:**
- Create: `scripts/research_gap_backfill.py`
- Test: `tests/test_audit_scripts.py`

- [ ] **Step 1: Write failing tests**

Add tests that create temporary SQLite databases and verify:
- `market_size_value` from `market_estimates` updates placeholder `research_fields`.
- LTV/CAC fields are filled as `industry_avg` from local benchmark data.
- Private fields such as `mau` are not fabricated.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_audit_scripts.py::AuditScriptsTests::test_research_gap_backfill_uses_market_estimates_and_benchmarks -q
```

Expected: fail because `scripts/research_gap_backfill.py` does not exist.

- [ ] **Step 3: Implement minimal script**

Create:
- `backfill_company(company, card_set="v4", research_db_path=None, dry_run=False) -> dict`
- CLI args: `--company`, `--set`, `--research-db`, `--dry-run`, `--json`
- SQLite updates to `research_fields` and `final_card_values` when tables/rows exist.

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m pytest tests/test_audit_scripts.py -q
```

Expected: pass.

### Task 2: Verify Against AIRIX

**Files:**
- No additional files.

- [ ] **Step 1: Dry run AIRIX**

Run:

```bash
python3 scripts/research_gap_backfill.py --company AIRIX --set v4 --dry-run --json
```

Expected: JSON report with no fabricated MAU/retention values.

- [ ] **Step 2: Run coverage checks**

Run:

```bash
python3 scripts/card_content_coverage_check.py --company AIRIX --set v4
python3 scripts/card_content_coverage_check.py --company AIRIX --set v3
```

Expected: both pass.
