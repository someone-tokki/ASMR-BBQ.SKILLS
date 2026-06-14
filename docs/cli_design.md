# CLI Design

This document defines the planned `asmr-bbq` command-line entry point. The CLI is an orchestrator over existing scripts; it must not replace the Skill's decision rules or duplicate lower-level logic.

## Boundary

```text
SKILL.md = agent decision policy
scripts/asmr_bbq.py = stable workflow entry point
scripts/*.py = individual tools
docs/*.md = operating rules and user-facing guidance
```

The CLI should make normal work easy. The Skill remains responsible for deciding when to ask the user, when to stop, when to switch route, and when to treat model output as unsafe.

## Commands

Planned commands:

```bash
python scripts/asmr_bbq.py init <work_dir>
python scripts/asmr_bbq.py status <work_dir>
python scripts/asmr_bbq.py run <work_dir> --interactive
python scripts/asmr_bbq.py resume <work_dir>
```

### `init`

Creates or refreshes project scaffolding.

Expected behavior:

1. Run `scripts/resolve_project_context.py <work_dir> --mkdir --json`.
2. Create `$PROJECT_ROOT/project_config.json` if missing.
3. Resolve learning paths with `scripts/resolve_learning_paths.py "$PROJECT_ROOT"`.
4. Report `SOURCE_PROJECT_DIR`, `PROJECT_ROOT`, and `FINAL_SUBTITLE_DIR`.

### `status`

Reads project state without changing subtitles.

Expected inputs:

- `$PROJECT_ROOT/project_config.json`
- `$PROJECT_ROOT/run_profile.json`
- ASR outputs
- translation outputs
- validation/risk/readability/QC reports
- export report
- `$PROJECT_ROOT/learning/work_record.md`

Expected output:

```text
project: RJxxxx
scope: confirmed / missing
asr: complete / missing / partial
translation: complete / missing / partial
validation: clean / warnings / errors / missing
qc: complete / missing
export: complete / missing
learning: work record exists / shared review pending / skipped
next action: ...
```

### `run --interactive`

Runs the standard guided path.

The first implementation should stop after preparing/confirming preflight choices if required. It should not silently launch expensive model calls without explicit scope and model confirmation.

Expected sequence:

```text
resolve_project_context
scan_audio_scope
preflight confirmation
prepare_run_profile
check_environment
resolve_asr_route
then call the selected workflow steps
```

### `resume`

Reads current state and runs the next safe step when unambiguous. If state is ambiguous, it should print the blocking condition and suggested command instead of guessing.

## Shared Corpus Review

The CLI must not automatically promote project findings into the shared corpus.

At finalization it should ask whether anything still needs correction and whether the user wants to organize the learning library now. If the user chooses learning-library organization, it should ask for one of:

```text
agent-assisted
user-review
skip
```

Then it should call:

```bash
python scripts/manage_shared_corpus_review.py "$PROJECT_ROOT" --choice <choice>
```

After the current project review choice is handled, it should list the review queue and surface the pending count. If the buffer is non-empty, the user can choose to process it immediately or defer it. Only later, after explicit approval of individual items, may an agent update the shared user learning library. The CLI or agent can list the queue and apply approved items with:

```bash
python scripts/manage_shared_corpus_review.py --list-queue --json-out "$PROJECT_ROOT/learning/review_queue_status.json"
python scripts/manage_shared_corpus_review.py --apply-approved --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"
```

The apply step only migrates candidates whose structured JSON decision is `approve`; all other items remain pending or rejected.

## Non-Goals For First Version

- No web UI.
- No full automatic speaker diarization.
- No automatic shared corpus promotion.
- No hidden fallback to the agent's own model for translation or QC.
- No broad refactor of existing workflow scripts.
