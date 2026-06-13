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
   - Learning-library maintenance or user questions about what gets learned: `docs/learning_library_guide.md`.
3. Choose the workflow:
   - With script or official text: read `docs/asmr_subtitle_workflow_with_script.md`.
   - Audio only: read `docs/asmr_subtitle_workflow_no_script.md`.
4. For platform/backend decisions, read `docs/platform_compatibility.md`.
5. When the user asks what this Skill can do or how to request work, refer them to `docs/user_guide.md`.
6. For long-running repository work inside this development repo, append concise recovery notes to `docs/implementation_log.md`. This log is development-only and should not be copied into a packaged Skill unless explicitly requested.

## Agent Responsibilities

- Preserve subtitle index count, order, start time, and end time unless the user explicitly asks for retiming.
- Non-negotiable quality floor:
  - Keep SRT indexes, order, start times, and end times unchanged.
  - Translation output must cover every target subtitle index exactly once.
  - Context halo items are for understanding only and must never be written into translated output or QC targets.
  - QC suggestions are candidates only. Do not directly auto-edit subtitles from QC output; after QC finishes, decide changes from source evidence, neighboring context, and project rules.
  - ASMR semantics, role relationships, action continuity, speaker turns, whispers, breaths, and onomatopoeia rhythm take priority over mechanical chunk compression.
  - Cached chunks may only be reused when content, target indexes, halo context, model, base URL, prompt/schema version, chunk settings, and context profile/signature match.
- Keep `.zh.srt` as the working format. Final output defaults to `.zh.vtt`; honor explicit user requests for `srt` or `both`.
- Default `SOURCE_PROJECT_DIR` to the source ASMR work directory resolved from the audio path or RJ parent folder. Default `PROJECT_ROOT` to `$SOURCE_PROJECT_DIR/subtitle_project/` so project artifacts and intermediate files do not scatter across the source folder root.
- Keep work artifacts under `PROJECT_ROOT` in named subfolders/files such as `asr_current/`, `srt_work/`, `qc_report.json`, and `project_config.json`. Keep deliverable subtitles under `FINAL_SUBTITLE_DIR`, which defaults to `$SOURCE_PROJECT_DIR/subtitles/`.
- Before ASR or translation, scan the source work folder for all target audio. Unless the user explicitly asks to translate only the main story or only selected files, include main tracks, EX/free talk, bonus, DLC, extras, promo/trial samples, and other audio-like folders equally. Do not skip audio merely because its filename lacks a main-story number, has a promo/trial/DLC label, or appears outside the main audio folder.
- Treat `$PROJECT_ROOT/model_profile.json` as the user-editable stage model preference file. It may specify separate backend/base_url/model values for ASR, translation, and QC. It is not a secrets file; never store API keys in it.
- Use scripts for checks instead of relying on eyeballing.
- Use `scripts/subtitle_io.py` for local SRT parsing/composition; core workflow scripts should not require the third-party `srt` package.
- Treat risk scans and QC reports as candidate evidence, not automatic truth.
- Treat the learning loop as a required finalization step for completed works. Before final response, produce a concise learning summary: what was added to project lessons, what was promoted to shared style/terms/risk references, what remained pending or project-only, and what was deliberately not learned to avoid polluting the corpus.
- Do not store API keys, model secrets, or private absolute paths in configs or logs.
- Do not mix ASR, partial files, reports, or review notes into final subtitle directories.
- After changing workflow docs, tools, QC policy, config behavior, platform/backend rules, or output rules, update this `SKILL.md` in the same turn so the agent entrypoint stays current. If a change is only a log, report, fixture, or generated artifact with no agent-facing behavior change, verify `SKILL.md` and state that no content update was needed.

## Standard Start

For a new work:

1. Resolve project context before creating any output files:

```bash
python scripts/resolve_project_context.py "/path/to/source_or_audio_root" --mkdir --json
```

Use the returned `work_id`, `project_root`, `source_project_dir`, and `final_subtitle_dir` as `WORK_ID`, `PROJECT_ROOT`, `SOURCE_PROJECT_DIR`, and `FINAL_SUBTITLE_DIR`. This script scans file paths and parent folder names for `RJxxxx`; a source folder named `RJxxxx` is enough to identify the work. By default, `PROJECT_ROOT` is `$SOURCE_PROJECT_DIR/subtitle_project/` and `FINAL_SUBTITLE_DIR` is `$SOURCE_PROJECT_DIR/subtitles/`. If no RJ exists, use the script's fallback work ID or ask the user.

2. Identify audio directories, script availability, existing `.ja.asr.srt`, existing `.zh.srt`/`.zh.vtt`, promo/trial/DLC/EX/bonus audio, desired output format, and the route from `docs/task_routing.md`.
   - Translation scope defaults to every discovered audio target under the source work folder. Only narrow the scope when the user explicitly says to translate the main story only, skip promo/trial, skip DLC/bonus, or use a specific file list.
   - If `WORK_ID` contains an RJ ID and network access is available/approved, fetch DLsite metadata with `scripts/fetch_dlsite_work_info.py` and save it as `$PROJECT_ROOT/dlsite_work_info.json`.
   - Treat DLsite title, circle, tags, and description as low-strength context, not as a transcript or proof against ASR/script evidence.
   - Before new ASR, scan audio variants with `scripts/select_asr_audio_source.py`. If a no-SE version is detected, prefer it for ASR because recognition is usually cleaner; if the user explicitly requests another version, use the user-selected version.
3. Default translation and QC model calls to an existing local OpenAI-compatible service port:
   - oMLX/common local server: `http://127.0.0.1:8000/v1`
   - LM Studio: `http://127.0.0.1:1234/v1`
   - Ollama: `http://127.0.0.1:11434/v1`
   On this user's machine, prefer `qwen3.6-27b` for translation and QC when that model is available; otherwise use the best configured local chat model.
4. Create or update `$PROJECT_ROOT/project_config.json` with `scripts/manage_project_config.py`, then create or update `$PROJECT_ROOT/model_profile.json` with `scripts/manage_model_profile.py` when the user wants per-stage model choices.
5. Use `--asr-backend auto` unless the user explicitly chooses `local-asr-api`, `python-whisper`, `mlx_whisper`, `external`, or another ASR backend. In auto mode, new ASR probes local platform API ports for `/audio/transcriptions` first, then configured `local-asr-api`, then the packaged Python Whisper route, then the controlled Python Whisper setup route.
6. Use `--translate-backend auto` unless the user explicitly chooses `ollama`, `omlx`, `lmstudio`, or another backend.
7. Run environment detection before ASR, translation, or QC:

```bash
python scripts/check_environment.py \
  --config "$PROJECT_ROOT/project_config.json" \
  --json-out "$PROJECT_ROOT/env_report.json"
```

If lightweight Python packages are missing, preview the install plan with:

```bash
python scripts/check_environment.py --dry-run-install --skip-api
```

When the user allows dependency changes, install missing Python packages into the active interpreter with:

```bash
python scripts/check_environment.py --install-missing-python --skip-api
```

Resolve `FAIL` items before production runs. `WARN` items may be acceptable if the chosen route has a fallback. If `*.ja.asr.srt` files already exist, missing local ASR backends such as `mlx_whisper` should not block translation, QC, or validation. Use `--require-asr` only when this run must create new ASR.

Before running new ASR, resolve the ASR route:

```bash
python scripts/resolve_asr_route.py \
  --config "$PROJECT_ROOT/project_config.json" \
  --require-new-asr \
  --json-out "$PROJECT_ROOT/asr_route_report.json"
```

If this command reports `setup_python_whisper_required`, use the packaged setup script after user approval:

```bash
python scripts/setup_whisper_backend.py \
  --install-package \
  --download-model \
  --model "$ASR_MODEL" \
  --json-out "$PROJECT_ROOT/whisper_setup_report.json"
```

If the route decision is `run_local_platform_asr_api` or `run_local_asr_api`, run `scripts/transcribe_openai_audio.py` against the reported `ASR_BASE_URL`. If the route decision is `run_python_whisper`, run `scripts/transcribe_whisper.py`.

ASR dependency rule: `--install-missing-python` is only for lightweight workflow packages such as `tqdm` and `PyYAML`. Use `setup_whisper_backend.py` for Python Whisper package/model setup. Do not use ad hoc pip/model-download commands for ASR backends outside the packaged setup route.

ASR resume rule: ASR scripts resume by default at the audio-file level. They skip an audio file when a parseable `<track>.ja.asr.srt` already exists, rebuild SRT from `<track>.ja.asr.json` when possible, and write/update `$ASR_DIR/asr_manifest.json` after each skip, success, or error. Use `--force` only when the user wants to regenerate an already completed ASR file; use `--no-resume` only when debugging checkpoint behavior.

ASR optimization rule: improve ASR cautiously and only when the selected backend/tool supports the option. Prefer no-SE audio for recognition unless the user chooses another version. For long or difficult audio, VAD may skip long silence or pure ambience, but it must not remove low-volume whispers, breaths, important pauses, or quiet dialogue. When splitting long audio, use overlap/stride to avoid boundary truncation, pass the previous segment transcript as prompt/context when supported, and record segment-level progress so interrupted runs can resume without discarding completed segments. Keep audio-file-level resume regardless. For ASMR breaths, ear-licking, kissing, and repeated sound effects, it is acceptable for final subtitles to simplify repeated noise; do not encourage ASR or later translation to generate meaningless repeated text walls.

Stage/model switching rule: ASR, translation, and QC run serially. At the start of each stage, resolve `backend`, `base_url`, `model`, and `interface` from `model_profile.json` when present, falling back to `project_config.json` and workflow defaults. Use:

```bash
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" asr --from-config
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" translate --from-config
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" qc --from-config
```

ASR must use a Whisper-class model through `/audio/transcriptions` or the Python Whisper script. Translation and QC must use a chat model through `/chat/completions`, with `qwen3.6-27b` as this user's preferred local default when available unless the user/project profile chooses another model. Do not carry an ASR model into translation/QC, and do not carry the translation/QC chat model into ASR. Before moving stages, confirm the previous job finished, output files are written, and the next API/model is reachable; release or switch loaded models if the local platform requires it.

Local model invocation discipline: when a workflow step says translation, mandatory model QC, or optional QC refinement, the agent must call the resolved configured model endpoint through the relevant script. The agent's own reasoning model is not a substitute for local/configured model QC, including second and later refinement rounds. The agent may orchestrate commands, read reports, compare evidence, and apply accepted corrections, but it must not silently replace `scripts/qc_srt_omlx.py` or the configured `/chat/completions` QC model with self-QC. If the configured local QC endpoint/model is unavailable, stop and report the missing service or ask for a backend change; do not "helpfully" continue by using the agent model as the QC model.

## Translation Flow

Use the selected workflow doc for exact commands. The normal sequence is:

1. ASR to Japanese `.ja.asr.srt`, or reuse existing `.ja.asr.srt` files if they already pass structure checks. New ASR requires a resolved ASR route from `scripts/resolve_asr_route.py`. When multiple audio variants exist, prefer no-SE audio for ASR unless the user chooses another version.
2. Structure check against expected SRT shape when files exist.
3. Translate to Chinese `.zh.srt`. Prefer semantic dynamic chunks with halo context: use `scripts/translate_srt_omlx.py` or `scripts/batch_translate_srt_omlx.py` with `--chunk-mode dynamic`, `--target-chars`, `--hard-chars`, `--min-chunk-size`, `--max-chunk-size`, `--context-before`, and `--context-after`. The halo is only for context; the model must output target indexes only, and every target index must be covered. Translation creates `<file>.zh.srt.flags.json` with optional focus flags such as `asr_uncertain`, `adult_term`, `speaker_ambiguous`, `pronoun_ambiguous`, `onomatopoeia`, `long_line`, `possible_noise`, and `needs_context`.
4. Run structure validation:

```bash
python scripts/validate_subtitles.py \
  --asr-dir "$ASR_DIR" \
  --zh-dir "$ZH_SRT_DIR" \
  --json-out "$PROJECT_ROOT/validate_report.json"
```

5. Run high-risk scan:

```bash
python scripts/scan_subtitle_risks.py \
  "$PROJECT_ROOT" \
  --json-out "$PROJECT_ROOT/risk_report.json"
```

6. Run ASMR readability check:

```bash
python scripts/subtitle_readability.py \
  "$ZH_SRT_DIR" \
  --max-cps 10 \
  --json-out "$PROJECT_ROOT/readability_report.json"
```

Readability warnings are advisory. ASMR listeners read slowly, so `10` Chinese chars/second is the default warning threshold; do not over-fragment subtitles just to lower CPS.

## QC Policy

- A first model QC pass after translation is mandatory.
- Model QC means calling the resolved configured QC chat model through `scripts/qc_srt_omlx.py` or an equivalent explicit local/configured `/chat/completions` route. It does not mean the agent reads subtitles and performs QC with its own model.
- QC runs with chunk-level resume by default. `scripts/qc_srt_omlx.py` stores successful chunk outputs under `<qc_report_stem>_chunks/` and records a manifest there, so interrupted QC runs should resume instead of repeating completed chunks.
- QC chunking defaults to `--chunk-mode dynamic`: the script shrinks chunks around long, high-risk, or dense ASMR content and can let simple short dialogue run larger. Use halo context with `--context-halo`; halo items are context only and must not be returned as QC targets.
- For speed-sensitive production runs, prefer `--qc-tier two-pass`: first run full light QC with larger semantic chunks, then run focused deep QC on high-risk spans selected from translation flags, risk terms, long lines, residual Japanese/garbage text, and neighboring context. Use `--qc-tier standard` for the old single-pass behavior, `light` for quick scans, and `deep` for focused reruns.
- QC cache signatures are chunk-local. They include target items, halo items, translation flags, model, base URL, prompt/schema version, chunk settings, and context, but do not include whole-file fingerprints. Existing manifests should be reused for stable chunk boundaries when possible so small subtitle edits only invalidate nearby affected chunks.
- The agent must correct all clear issues from `qc_report.json`, then rerun structure validation, risk scan, and readability checks.
- If the user is still dissatisfied after the mandatory QC pass, treat additional correction as an optional QC refinement feature, not as the baseline QC step.
- Start each optional refinement round with `scripts/manage_qc_refinement.py start`, using `--mode auto` for model-led contextual QC or `--mode guided --user-guidance "..."` when the user provides style notes, issue descriptions, or desired direction.
- Every optional refinement round, including the second round and any later rounds, must run focused QC through the resolved configured QC backend/model. Agent self-review can prepare focus and accept/reject decisions, but it is not model QC.
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

- ASR defaults to local platform API probing first: oMLX/LM Studio/Ollama or another configured OpenAI-compatible base URL may be used for ASR only when `/audio/transcriptions` is reachable. If not, try configured `local-asr-api`, then packaged Python Whisper, then controlled setup.
- Translation and QC default to existing local chat service ports when configured/available, using `qwen3.6-27b` as this user's preferred local model when available.
- Windows/WSL default to Ollama for translation and QC when available.
- If Ollama is unavailable and `translate_backend=auto`, fall back to another available OpenAI-compatible backend.
- If the project explicitly sets `translate_backend=ollama`, missing Ollama is a blocker.
- macOS may continue using oMLX or another OpenAI-compatible local API.
- `check_environment.py` detects Python packages, scripts, external commands, ASR/backend availability, paths, output settings, and local API reachability.
- By default `check_environment.py` is read-only. With `--install-missing-python`, it may install small Python packages listed in its dependency table, such as `tqdm` and `PyYAML`, into the active interpreter.
- It must not silently install Ollama/oMLX, ASR backends, system packages, models, or start services; report those as user/agent setup actions.
- Translation and QC should use the selected local OpenAI-compatible chat service such as oMLX/Ollama/LM Studio.
- If local platform/local ASR API is unavailable and local Python `whisper` is unavailable, use `scripts/setup_whisper_backend.py` to install `openai-whisper` and download/cache the selected model after user approval.
- Local service ASR via `/audio/transcriptions` may be auto-selected only after `scripts/resolve_asr_route.py` verifies the endpoint. A chat-only endpoint must not be treated as ASR-capable.
- `asr_backend=auto` is not permission to install random ASR packages or guess local binaries; it is permission to probe known local platform ASR endpoints, then use the packaged Python Whisper route and its setup script if needed.

## Packaging Boundary

When preparing this as a formal Skill, include `SKILL.md`, `agents/`, `scripts/`, `references/`, `data/`, `docs/user_guide.md`, `docs/learning_library_guide.md`, and workflow/reference docs that the Skill directly links to. Exclude `generated_subtitles/`, `docs/implementation_log.md`, caches, local model files, private configs, and any per-work reports unless the user explicitly asks for a development snapshot.

## Finalization

Before final delivery:

1. Confirm structure validation has no errors.
2. Confirm high-risk findings are handled or explicitly recorded.
3. Confirm readability warnings are reviewed, especially high CPS and over-fragmentation.
4. Confirm mandatory QC is completed and clear issues are corrected.
5. Run the learning loop before final response:
   - Read `docs/learning_library_guide.md` and classify every candidate lesson as `confirmed`, `project-only`, `pending`, or `false-positive`.
   - Extract reusable lessons from final subtitles, `qc_report.json`, risk findings, readability reports, and manual corrections.
   - Add a `references/project-lessons.md` entry for every completed work, even when no new global rule is found.
   - Extract reusable project lessons into the shared references: durable terminology to `references/terms.md`, style/pacing rules to `references/style.md`, and easy-mistake/ASR-risk context or false-positive notes to `references/risk-notes.md`.
   - Add mechanically scannable confirmed risks to `data/subtitle_risk_patterns.json`.
   - Mark uncertain lessons in `references/pending.md` instead of treating them as confirmed rules.
   - Use `scripts/update_learning_library.py` to draft or append the per-project learning record, then manually fill reusable lessons before delivery.
   - Do a learning self-check: if no shared reference was updated, explicitly record whether there were no reusable lessons, only project-specific lessons, only pending evidence, or a user request not to globalize the lesson.
6. Convert/export according to `output_format`:
   - `vtt`: final `.zh.vtt`.
   - `srt`: final `.zh.srt`.
   - `both`: both `.zh.srt` and `.zh.vtt`.
   Use `scripts/export_final_subtitles.py "$ZH_SRT_DIR" "$FINAL_SUBTITLE_DIR" --format "$OUTPUT_FORMAT" --glob "*.zh.srt" --overwrite` for final export.
7. Export final subtitles to `$FINAL_SUBTITLE_DIR`, defaulting to `$SOURCE_PROJECT_DIR/subtitles/`, and keep that directory limited to final `.zh.vtt/.zh.srt` files.
8. Run `scripts/validate_subtitles.py --final-dir "$FINAL_SUBTITLE_DIR"` after export.

Report the final paths, output format, QC status, unresolved items, and a learning summary that names updated files and pending/project-only decisions.
