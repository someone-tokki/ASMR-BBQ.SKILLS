# ASMR-BBQ.SKILLS

Agent-led Japanese ASMR / doujin voice subtitle workflow for Simplified Chinese subtitles.

This project helps an agent or advanced user:

- detect audio scope in RJ work folders;
- reuse or create Japanese ASR subtitles;
- translate Japanese ASMR subtitles into natural Simplified Chinese;
- keep terminology, tone, and ASMR readability consistent;
- run mandatory model QC and risk checks;
- export final `.zh.vtt` or `.zh.srt` subtitles;
- preserve intermediate artifacts for resume, review, and learning.

## Current Entry Point

The Skill entry point is `SKILL.md`. For now, agents orchestrate the workflow by reading `SKILL.md`, `docs/task_routing.md`, and the matching workflow document, then calling scripts under `scripts/`.

The planned standalone CLI entry point is documented in `docs/cli_design.md`:

```bash
python scripts/asmr_bbq.py status /path/to/RJxxxxxx
python scripts/asmr_bbq.py run /path/to/RJxxxxxx --interactive
```

Until that CLI exists, use the workflow scripts directly through the Skill instructions.

## Output Layout

By default, project files stay inside the source ASMR work folder:

```text
RJ012345/
  subtitle_project/   # ASR, SRT work files, run profile, QC, reports, learning drafts
  subtitles/          # final .zh.vtt/.zh.srt deliverables
```

`subtitle_project/` is for recoverable working artifacts. `subtitles/` is the final deliverable directory.

## Shared Local State

The installed Skill package is treated as read-only during ordinary subtitle work. User-level state lives outside the Skill package so multiple local agents can share it.

```text
~/ASMR-Subtitle-Translator/
  learning/           # shared user learning library and review queue
  asr/                # shared Python Whisper venv and model cache
```

Defaults can be overridden with:

```bash
ASMR_SUBTITLE_LEARNING_DIR=/path/to/learning
ASMR_SUBTITLE_ASR_DIR=/path/to/asr
```

## Quality Rules

- Keep SRT indexes, order, start times, and end times stable unless retiming is explicit.
- Translation must cover every target subtitle index.
- Model QC suggestions are candidate evidence, not automatic edits.
- `draft` is allowed to be fast, but must not pretend to be premium quality.
- Project findings are not automatically promoted to the shared corpus.

## Shared Corpus Review

At wrap-up, the agent should ask whether anything still needs correction and whether the user wants to organize the learning library now. If the user chooses learning-library organization, it should ask whether to:

```text
1. let the agent assist with shared corpus review;
2. add the project to the review queue for user review;
3. skip shared corpus review for this work.
```

Only explicitly approved items may be promoted to the shared user learning library. Project-only, uncertain, or persona-specific findings stay in `$PROJECT_ROOT/learning/`.

After handling the current project's review choice, the agent should list the review queue. If pending packets already exist, it should ask whether to process that buffer now or leave it for later.

The review mechanism has an index, so later agents can find pending work:

```bash
python scripts/manage_shared_corpus_review.py \
  --list-queue \
  --json-out "$PROJECT_ROOT/learning/review_queue_status.json"
```

After a user or agent reviews `$PROJECT_ROOT/learning/shared_corpus_review.json` and marks specific candidates as `approve`, apply only those approved items with:

```bash
python scripts/manage_shared_corpus_review.py \
  --apply-approved \
  --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"
```

## Documentation

- `docs/task_routing.md`: choose the correct workflow.
- `docs/preflight_confirmation.md`: required user confirmation before model calls.
- `docs/asmr_subtitle_workflow_with_script.md`: workflow when a script or official text exists.
- `docs/asmr_subtitle_workflow_no_script.md`: workflow for audio-only projects.
- `docs/learning_library_guide.md`: learning library and shared corpus review policy.
- `docs/platform_compatibility.md`: backend and platform rules.
- `docs/cli_design.md`: planned one-command CLI design.
