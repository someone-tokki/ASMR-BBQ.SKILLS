---
name: asmr-subtitle-translator
description: Use this skill when an agent needs to create, translate, QC, validate, or package Japanese ASMR subtitles into natural Simplified Chinese subtitles, including projects with or without scripts, ASR alignment, risk scanning, readability checks, mandatory model QC, output format selection, and Windows/WSL/Ollama compatibility.
---

# ASMR Subtitle Translator

Use this skill to run an agent-led Japanese ASMR subtitle workflow. The agent is the orchestrator; scripts are guardrails for validation, reporting, conversion, and repeatable checks.

## Load Order

1. Read `docs/task_routing.md` to classify the request before choosing a workflow.
2. Read `docs/asmr_translation_corpus.md` as the corpus index, then load only the needed references:
   - Translation or subtitle editing: `references/style.md` and `references/terms.md`.
   - Risk scan, QC, or correction: `references/risk-notes.md` and, when terminology matters, `references/terms.md`.
   - Learning-loop updates: `references/project-lessons.md` and `references/pending.md` as needed.
3. Choose the workflow:
   - With script or official text: read `docs/asmr_subtitle_workflow_with_script.md`.
   - Audio only: read `docs/asmr_subtitle_workflow_no_script.md`.
4. For platform/backend decisions, read `docs/platform_compatibility.md`.
5. For long-running repository work inside this development repo, append concise recovery notes to `docs/implementation_log.md`. This log is development-only and should not be copied into a packaged Skill unless explicitly requested.

## Agent Responsibilities

- Preserve subtitle index count, order, start time, and end time unless the user explicitly asks for retiming.
- Keep `.zh.srt` as the working format. Final output defaults to `.zh.vtt`; honor explicit user requests for `srt` or `both`.
- Use scripts for checks instead of relying on eyeballing.
- Use `scripts/subtitle_io.py` for local SRT parsing/composition; core workflow scripts should not require the third-party `srt` package.
- Treat risk scans and QC reports as candidate evidence, not automatic truth.
- Do not store API keys, model secrets, or private absolute paths in configs or logs.
- Do not mix ASR, partial files, reports, or review notes into final subtitle directories.
- After changing workflow docs, tools, QC policy, config behavior, platform/backend rules, or output rules, update this `SKILL.md` in the same turn so the agent entrypoint stays current. If a change is only a log, report, fixture, or generated artifact with no agent-facing behavior change, verify `SKILL.md` and state that no content update was needed.

## Standard Start

For a new work:

1. Identify `work_id`, audio directories, script availability, existing `.ja.asr.srt`, existing `.zh.srt`/`.zh.vtt`, promo/trial audio, desired output format, and the route from `docs/task_routing.md`.
   - If `work_id` contains an RJ ID and network access is available/approved, fetch DLsite metadata with `scripts/fetch_dlsite_work_info.py` and save it as `generated_subtitles/<work_id>/dlsite_work_info.json`.
   - Treat DLsite title, circle, tags, and description as low-strength context, not as a transcript or proof against ASR/script evidence.
   - Before new ASR, scan audio variants with `scripts/select_asr_audio_source.py`. If a no-SE version is detected, prefer it for ASR because recognition is usually cleaner; if the user explicitly requests another version, use the user-selected version.
2. Create or update `generated_subtitles/<work_id>/project_config.json` with `scripts/manage_project_config.py`.
3. Use `--asr-backend auto` unless the user explicitly chooses `mlx_whisper`, `external`, or another ASR backend.
4. Use `--translate-backend auto` unless the user explicitly chooses `ollama`, `omlx`, or another backend.
5. Run environment detection before ASR, translation, or QC:

```bash
python scripts/check_environment.py \
  --config "generated_subtitles/<work_id>/project_config.json" \
  --json-out "generated_subtitles/<work_id>/env_report.json"
```

If lightweight Python packages are missing, preview the install plan with:

```bash
python scripts/check_environment.py --dry-run-install --skip-api
```

When the user allows dependency changes, install missing Python packages into the active interpreter with:

```bash
python scripts/check_environment.py --install-missing-python --skip-api
```

Resolve `FAIL` items before production runs. `WARN` items may be acceptable if the chosen route has a fallback. If `*.ja.asr.srt` files already exist, missing local ASR backends such as `mlx_whisper` should not block translation, QC, or validation. Use `--require-asr` when checking an environment that must run new ASR.

## Translation Flow

Use the selected workflow doc for exact commands. The normal sequence is:

1. ASR to Japanese `.ja.asr.srt`, or reuse existing `.ja.asr.srt` files if they already pass structure checks. When multiple audio variants exist, prefer no-SE audio for ASR unless the user chooses another version.
2. Structure check against expected SRT shape when files exist.
3. Translate to Chinese `.zh.srt`.
4. Run structure validation:

```bash
python scripts/validate_subtitles.py \
  --asr-dir "$ASR_DIR" \
  --zh-dir "$ZH_SRT_DIR" \
  --json-out "generated_subtitles/<work_id>/validate_report.json"
```

5. Run high-risk scan:

```bash
python scripts/scan_subtitle_risks.py \
  "generated_subtitles/<work_id>" \
  --json-out "generated_subtitles/<work_id>/risk_report.json"
```

6. Run ASMR readability check:

```bash
python scripts/subtitle_readability.py \
  "$ZH_SRT_DIR" \
  --max-cps 10 \
  --json-out "generated_subtitles/<work_id>/readability_report.json"
```

Readability warnings are advisory. ASMR listeners read slowly, so `10` Chinese chars/second is the default warning threshold; do not over-fragment subtitles just to lower CPS.

## QC Policy

- A first model QC pass after translation is mandatory.
- The agent must correct all clear issues from `qc_report.json`, then rerun structure validation, risk scan, and readability checks.
- If the user is still dissatisfied after the mandatory QC pass, treat additional correction as an optional QC refinement feature, not as the baseline QC step.
- Start each optional refinement round with `scripts/manage_qc_refinement.py start`, using `--mode auto` for model-led contextual QC or `--mode guided --user-guidance "..."` when the user provides style notes, issue descriptions, or desired direction.
- Each refinement round must generate `context_profile.md` from project metadata, DLsite metadata when available, track names, subtitle samples, focus, and user guidance; keep each round's reports under `qc_refinement/round_NN/`.
- Agent correction must be evidence-driven:
  - With script: script > JA ASR > neighboring context > corpus/rules > QC suggestion > agent judgment.
  - Without script: JA ASR + neighboring context + title/setting > corpus/rules > QC suggestion > agent judgment.
- The agent must not use its own model judgment alone to rejudge QC suggestions.
- Human review is optional and used for second-pass QC, unresolved items, conflicting suggestions, or direct user intervention.
- When human review is needed, generate a review template with `scripts/review_qc_report.py`.
- For tool-assisted QC correction, generate normalized review items with `scripts/review_qc_report.py`, let the agent mark evidence-backed items as `accept`, `reject`, or `defer`, then apply only accepted items with `scripts/apply_qc_decisions.py --apply`.
- After applying accepted QC decisions, rerun structure validation, risk scan, and readability checks.
- Repeat optional QC refinement rounds only while the user asks for more polish or unresolved issues remain; stop when accepted changes are exhausted, checks are clean enough, or the user is satisfied.

## Platform And Backend Rules

- Windows/WSL default to Ollama for translation and QC when available.
- If Ollama is unavailable and `translate_backend=auto`, fall back to another available OpenAI-compatible backend.
- If the project explicitly sets `translate_backend=ollama`, missing Ollama is a blocker.
- macOS may continue using oMLX or another OpenAI-compatible local API.
- `check_environment.py` detects Python packages, scripts, external commands, ASR/backend availability, paths, output settings, and local API reachability.
- By default `check_environment.py` is read-only. With `--install-missing-python`, it may install small Python packages listed in its dependency table, such as `tqdm` and `PyYAML`, into the active interpreter.
- It must not silently install Ollama/oMLX, ASR backends, system packages, models, or start services; report those as user/agent setup actions.

## Packaging Boundary

When preparing this as a formal Skill, include `SKILL.md`, `agents/`, `scripts/`, `references/`, `data/`, and workflow/reference docs that the Skill directly links to. Exclude `generated_subtitles/`, `docs/implementation_log.md`, caches, local model files, private configs, and any per-work reports unless the user explicitly asks for a development snapshot.

## Finalization

Before final delivery:

1. Confirm structure validation has no errors.
2. Confirm high-risk findings are handled or explicitly recorded.
3. Confirm readability warnings are reviewed, especially high CPS and over-fragmentation.
4. Confirm mandatory QC is completed and clear issues are corrected.
5. Run the learning loop before final response:
   - Extract reusable lessons from final subtitles, `qc_report.json`, risk findings, readability reports, and manual corrections.
   - Add a `references/project-lessons.md` entry for every completed work, even when no new global rule is found.
   - Extract reusable project lessons into the shared references: durable terminology to `references/terms.md`, style/pacing rules to `references/style.md`, and easy-mistake/ASR-risk context or false-positive notes to `references/risk-notes.md`.
   - Add mechanically scannable confirmed risks to `data/subtitle_risk_patterns.json`.
   - Mark uncertain lessons in `references/pending.md` instead of treating them as confirmed rules.
   - Use `scripts/update_learning_library.py` to draft or append the per-project learning record, then manually fill reusable lessons before delivery.
6. Convert/export according to `output_format`:
   - `vtt`: final `.zh.vtt`.
   - `srt`: final `.zh.srt`.
   - `both`: both `.zh.srt` and `.zh.vtt`.
7. Keep final subtitle directories named after the original audio folders and containing only final subtitle files for that folder.

Report the final paths, output format, QC status, unresolved items, and what was learned or added to the corpus/risk library.
