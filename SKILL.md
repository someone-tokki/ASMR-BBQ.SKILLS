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
   - Learning-loop updates: `docs/learning_library_guide.md`, then the resolved user learning library and `$PROJECT_ROOT/learning/` paths as needed.
   - Learning-library maintenance or user questions about what gets learned: `docs/learning_library_guide.md`.
3. Choose the workflow:
   - With script or official text: read `docs/asmr_subtitle_workflow_with_script.md`.
   - Audio only: read `docs/asmr_subtitle_workflow_no_script.md`.
4. For platform/backend decisions, read `docs/platform_compatibility.md`.
5. Before any production ASR, translation, or QC model call, read `docs/preflight_confirmation.md`.
6. For stereo/multi-speaker ASMR ASR gap recovery, read `docs/channel_recovery.md`.
7. When the user asks what this Skill can do or how to request work, refer them to `docs/user_guide.md`.
8. For long-running repository work inside this development repo, append concise recovery notes to `docs/implementation_log.md`. This log is development-only and should not be copied into a packaged Skill unless explicitly requested.

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
- Before ASR or translation, scan the source work folder for all target audio folders with `scripts/scan_audio_scope.py`, list the discovered folders to the user, and ask which folders or files should be translated in this run. Do not skip audio merely because its filename lacks a main-story number, has a promo/trial/DLC label, or appears outside the main audio folder. Process all discovered audio only when the user confirms `all`; otherwise honor the selected folders/files recorded in `run_profile.json`.
- Treat `$PROJECT_ROOT/model_profile.json` as the user-editable stage model preference file. It may specify separate backend/base_url/model values for ASR, translation, and QC. It is not a secrets file; never store API keys in it.
- Use scripts for checks instead of relying on eyeballing.
- Use `scripts/subtitle_io.py` for local SRT parsing/composition; core workflow scripts should not require the third-party `srt` package.
- Treat risk scans and QC reports as candidate evidence, not automatic truth.
- Treat the learning loop as a required finalization step for completed works. At wrap-up, keep the user-facing prompt natural: ask whether anything still needs correction, and whether they want the learning library organized now. If corrections are requested, handle them before shared-corpus review. Before final response, produce a concise learning summary: what was added to the project work record, what remains pending or project-only, what is eligible for shared corpus review, and what was deliberately not learned to avoid polluting the corpus. Do not automatically promote project findings to the user long-term corpus; when the user wants learning-library organization, ask whether they want agent-assisted review, user review queue only, or no shared corpus review for this work. Also check the shared corpus review queue and, if pending entries exist, ask whether to process the buffer now or defer it.
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
   - Run `scripts/scan_audio_scope.py "$SOURCE_PROJECT_DIR" --json-out "$PROJECT_ROOT/audio_scope_report.json"` and ask the user which listed audio folders/files should be translated. Translation scope is not confirmed until it is written to `$PROJECT_ROOT/run_profile.json`.
   - If `WORK_ID` contains an RJ ID and network access is available/approved, fetch DLsite metadata with `scripts/fetch_dlsite_work_info.py` and save it as `$PROJECT_ROOT/dlsite_work_info.json`.
   - Treat DLsite title, circle, tags, and description as low-strength context, not as a transcript or proof against ASR/script evidence.
   - Before new ASR, scan audio variants with `scripts/select_asr_audio_source.py`. User-selected audio always wins. Otherwise, when no-SE files can be matched to regular audio by track, use only matched no-SE files with `requires_review=false` for ASR by default because recognition is usually cleaner. If a matched no-SE track has both MP3 and WAV candidates, prefer MP3 for faster ASR unless warnings suggest a cropped/preview/placeholder file; keep the final subtitle names mapped to the original work tracks.
3. Default translation and QC model calls to an existing local OpenAI-compatible service port:
   - oMLX/common local server: `http://127.0.0.1:8000/v1`
   - LM Studio: `http://127.0.0.1:1234/v1`
   - Ollama: `http://127.0.0.1:11434/v1`
   For bulk translation, prefer a non-reasoning instruct/chat model such as `Qwen2.5-32B-Instruct-GGUF-Q4_K_M` or another verified fast Japanese/Chinese model. Qwen3.x reasoning models may spend hidden thinking tokens even when visible `<think>` output is absent; use them for bulk translation only after behavior probing confirms low latency, stable JSON, and no blank responses.
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

`setup_whisper_backend.py` uses a shared user ASR environment by default: `${ASMR_SUBTITLE_ASR_DIR:-~/ASMR-Subtitle-Translator/asr}/openai-whisper-venv`. Do not install openai-whisper into each agent's active Python interpreter unless the user explicitly passes `--no-shared`. Different Codex/Claude/agent installations on the same machine should reuse this shared venv and shared Whisper model cache.

If the route decision is `run_local_platform_asr_api` or `run_local_asr_api`, run `scripts/transcribe_openai_audio.py` against the reported `ASR_BASE_URL`. If the route decision is `run_python_whisper`, run `scripts/transcribe_whisper.py`.

ASR dependency rule: `--install-missing-python` is only for lightweight workflow packages such as `tqdm` and `PyYAML`. Use `setup_whisper_backend.py` for Python Whisper package/model setup. The default target is the shared user ASR venv, not the current agent interpreter. Do not use ad hoc pip/model-download commands for ASR backends outside the packaged setup route.

ASR resume rule: ASR scripts resume by default at the audio-file level. They skip an audio file when a parseable `<track>.ja.asr.srt` already exists, rebuild SRT from `<track>.ja.asr.json` when possible, and write/update `$ASR_DIR/asr_manifest.json` after each skip, success, or error. Use `--force` only when the user wants to regenerate an already completed ASR file; use `--no-resume` only when debugging checkpoint behavior.

ASR optimization rule: improve ASR cautiously and only when the selected backend/tool supports the option. Prefer user-selected audio first; otherwise prefer no-SE audio only when track mapping is clear. If no-SE MP3 and WAV versions are both available for the same matched track, use MP3 first for speed, but fall back to WAV or ask for review when the MP3 looks cropped, preview-only, unusually tiny, or otherwise suspicious. For long or difficult audio, use `scripts/prepare_asr_audio_cache.py` to create `$PROJECT_ROOT/asr_prepared/` segment plans and optional normalized 16k mono audio. VAD may skip long silence or pure ambience only when supported and explicitly chosen, but it must not remove low-volume whispers, breaths, important pauses, or quiet dialogue. When splitting long audio, use overlap/stride to avoid boundary truncation, pass the previous segment transcript as prompt/context when supported, and record segment-level progress so interrupted runs can resume without discarding completed segments. Keep audio-file-level resume regardless. For ASMR breaths, ear-licking, kissing, and repeated sound effects, it is acceptable for final subtitles to simplify repeated noise; do not encourage ASR or later translation to generate meaningless repeated text walls.

ASR timestamp repair rule: Whisper-style small timeline overlaps belong to the ASR repair stage, not the translation or QC stages. Use `scripts/repair_asr_timestamps.py` after ASR and before translation when `validate_subtitles.py` reports `time_overlap`. This tool may auto-fix only small overlaps by clipping the previous subtitle end to the current subtitle start while preserving index order and subtitle text. Large overlaps, invalid ranges, or overlaps that would make a subtitle too short must remain review-only. When matching `.zh.srt` files already exist, do not silently fix `.ja.asr.srt` alone because that would break JA/ZH pair timeline alignment; report the issue or rerun the downstream translation/QC chain after the repair.

## Mandatory Preflight Confirmation

Before starting production ASR, translation, or QC model calls, the agent must complete Preflight unless the current user request already explicitly provides every required choice. Auto mode is not user confirmation. Agent-selected defaults are only a proposal unless the user explicitly says to use defaults, "you decide", "no need to ask", or equivalent.

The agent must:

1. Run `scripts/scan_audio_scope.py "$SOURCE_PROJECT_DIR" --json-out "$PROJECT_ROOT/audio_scope_report.json"`.
2. List the discovered audio folders to the user and ask which folders or files should be translated. Trial, promo, DLC, EX, bonus, and other side folders must be shown rather than silently skipped. No-SE folders are ASR-source candidates, not automatic translation scope.
3. Confirm quality mode: `draft`, `standard`, `premium`, or `polish`.
4. Confirm ASR backend/base URL/model and whether existing `.ja.asr.srt` should be reused.
5. Confirm translation backend/base URL/model.
6. Confirm QC backend/base URL/model.
7. Confirm output format: `vtt`, `srt`, or `both`.
8. Write the confirmed choices to `$PROJECT_ROOT/run_profile.json` with `scripts/prepare_run_profile.py`, including `--confirmation-source`, `--confirmation-text`, `--preflight-questions-presented`, and either `--audio-scope-report` or `--audio-scope-summary`.
9. Sync confirmed stage model choices with `scripts/manage_model_profile.py sync-run-profile "$PROJECT_ROOT"` when a model profile should drive later commands.
10. Before each model stage, run `scripts/check_preflight.py "$PROJECT_ROOT" --stage <asr|translate|qc>`.

If any choice is missing, ambiguous, or inconsistent with the detected environment, stop and ask the user before model calls. If the user says "default" or "you decide", choose reasonable defaults, show the final choices, write `run_profile.json` with `confirmation_source=user_default_authorized`, and only then continue.

Production ASR, translation, and QC scripts accept `--project-root "$PROJECT_ROOT"` and will enforce the preflight gate when it is supplied. Formal workflow commands must pass `--project-root`; use `--no-preflight-check` only for isolated debugging or fixtures, not for normal subtitle production.

Quality mode mapping:

- `draft`: `turbo` translation preset, QC tier `off`, fastest rough subtitle route.
- `standard`: `fast` translation preset, QC tier `two-pass`, normal recommended route.
- `premium`: `safe` translation preset, QC tier `two-pass`, slower and stricter.
- `polish`: `safe` translation preset, QC tier `two-pass`, reuse existing ASR/translation when possible.

Channel recovery rule: for suspected two-person stereo whisper gaps, do not run full-track left/right ASR by default. First use the normal main ASR timeline. After main ASR, the agent may run `scripts/detect_channel_activity.py` as a lightweight scan to find candidate windows from left/right energy plus main-ASR gaps or weak main-ASR coverage. Weak coverage includes output like `...`, `……`, very short breaths/onomatopoeia, trigger sounds, or very low text density over a long active audio span. This scan is candidate-only and may confuse ASMR effects with speech. If candidates are marked for user disambiguation, explicitly warn the user that the segment may be speech or may be ASMR sound effects/BGM/breaths and needs review. If the user points to missing speech, QC/listening finds a gap/weak-coverage span, or the detector finds candidates worth checking, use `scripts/prepare_channel_recovery.py` to create left/right candidate clips under `$PROJECT_ROOT/channel_recovery/<track>/`. Transcribe those clips with the resolved ASR backend, review them as candidates, and only merge clear missing speech after evidence review. Channel recovery output must not automatically overwrite the main ASR or final subtitles.

Stage/model switching rule: ASR, translation, and QC run serially. At the start of each stage, resolve `backend`, `base_url`, `model`, and `interface` from `model_profile.json` when present, falling back to `project_config.json` and workflow defaults. Use:

```bash
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" asr --from-config
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" translate --from-config
python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" qc --from-config
```

ASR must use a Whisper-class model through `/audio/transcriptions` or the Python Whisper script. Translation and QC must use a chat model through `/chat/completions`. For bulk translation, default toward non-reasoning instruct models; do not assume Qwen3.x no-thinking controls work on every backend. Do not carry an ASR model into translation/QC, and do not carry the translation/QC chat model into ASR.

Before translation, mandatory QC, or any additional QC refinement, run `scripts/prepare_model_stage.py` for the target chat stage. This is separate from Preflight: Preflight confirms which models the run intends to use; model-stage preparation confirms the target local model is reachable and can answer right now. If translation and QC use different models, the QC stage check is a hard gate:

```bash
python scripts/prepare_model_stage.py "$PROJECT_ROOT" translate --previous-stage asr --from-config --api-key "$TRANSLATE_API_KEY"
python scripts/prepare_model_stage.py "$PROJECT_ROOT" qc --previous-stage translate --from-config --api-key "$TRANSLATE_API_KEY"
```

When the selected translation model is Qwen3.x, reasoning-class, unknown, or newly configured, add behavior probing before bulk work:

```bash
python scripts/prepare_model_stage.py "$PROJECT_ROOT" translate --previous-stage asr --from-config --api-key "$TRANSLATE_API_KEY" --probe-behavior --require-non-thinking --json-out "$PROJECT_ROOT/model_stage_translate.json"
```

If behavior probing reports `too_slow_reasoning_model`, `no_thinking_not_effective`, blank responses, or unstable JSON, stop and recommend a non-reasoning instruct model instead of trying to solve the problem only by changing chunk size. If it reports `model_not_found`, use the exact model id from `/models`. If it reports `model_load_failed` or the backend logs show weight shape/architecture errors, treat that as a backend/model compatibility failure, not as proof that no-thinking controls broke all reasoning models. If plain requests work but `no_thinking_payload_rejected` appears, then the backend/model does not accept this Skill's no-thinking payload and must not be used for structured subtitle work until the payload is adapted.

After the model-stage check, resolve model-aware chunk defaults before translation or QC:

```bash
python scripts/resolve_chunk_profile.py "$PROJECT_ROOT" translate --model-stage-report "$PROJECT_ROOT/model_stage_translate.json" --json-out "$PROJECT_ROOT/chunk_profile_translate.json"
python scripts/resolve_chunk_profile.py "$PROJECT_ROOT" qc --model-stage-report "$PROJECT_ROOT/model_stage_qc.json" --json-out "$PROJECT_ROOT/chunk_profile_qc.json"
```

Use the resulting `defaults` as upper bounds for `--target-chars`, `--hard-chars`, chunk sizes, halo/context, QC tier, worker count, and reasoning token budget. Semantic continuity remains primary; model-aware profiles must not fragment ASMR dialogue mechanically.

If the stage check reports `FAIL`, stop before the model call. HTTP 500 from `/chat/completions` commonly means the previous stage model still occupies memory, the target model failed to load or is too large, the backend cannot hot-switch from the request `model` field, the model id is wrong, or the service needs a manual reload/restart. When a plain minimal request and a no-thinking request both fail with the same 5xx, diagnose model/backend loading before blaming the no-thinking prompt controls. Ask the user to release/unload the previous model or manually switch/load the target model, then rerun the stage check. Do not keep blind-retrying, and do not substitute the agent's own model.

Local model invocation discipline: when a workflow step says translation, mandatory model QC, or optional QC refinement, the agent must call the resolved configured model endpoint through the relevant script. The agent's own reasoning model is not a substitute for local/configured model QC, including second and later refinement rounds. The agent may orchestrate commands, read reports, compare evidence, and apply accepted corrections, but it must not silently replace `scripts/qc_srt_omlx.py` or the configured `/chat/completions` QC model with self-QC. If the configured local QC endpoint/model is unavailable, stop and report the missing service or ask for a backend change; do not "helpfully" continue by using the agent model as the QC model.

## Translation Flow

Use the selected workflow doc for exact commands. The normal sequence is:

1. ASR to Japanese `.ja.asr.srt`, or reuse existing `.ja.asr.srt` files if they already pass structure checks. New ASR requires a resolved ASR route from `scripts/resolve_asr_route.py`. When multiple audio variants exist, use `scripts/select_asr_audio_source.py`: user-selected audio wins; otherwise prefer matched no-SE files, with no-SE MP3 preferred over no-SE WAV for the same track unless warnings require review.
2. Structure check against expected SRT shape when files exist.
3. If structure validation reports minor `time_overlap` issues in `.ja.asr.srt`, optionally run `scripts/repair_asr_timestamps.py` before translation. This is an ASR timeline repair step, not a translation/QC edit step. After repair, rerun `validate_subtitles.py`.
4. Translate to Chinese `.zh.srt`. Prefer semantic dynamic chunks with halo context: use `scripts/translate_srt_omlx.py` or `scripts/batch_translate_srt_omlx.py` with `--preset fast` for standard work, `safe` for premium work, or `turbo` for draft work. These presets expand to dynamic chunk settings with `--target-chars`, `--hard-chars`, `--min-chunk-size`, `--max-chunk-size`, `--context-before`, and `--context-after`. The halo is only for context; the model must output target indexes only, and every target index must be covered. Translation creates `<file>.zh.srt.flags.json` with optional focus flags such as `asr_uncertain`, `adult_term`, `speaker_ambiguous`, `pronoun_ambiguous`, `onomatopoeia`, `long_line`, `possible_noise`, and `needs_context`. Translation chunk cache is stored under `<output_stem>.translate_chunks/` by default and may only be reused when the chunk signature matches content, target indexes, halo, model, base URL, prompt/schema version, and chunk settings.
5. Run structure validation:

```bash
python scripts/validate_subtitles.py \
  --asr-dir "$ASR_DIR" \
  --zh-dir "$ZH_SRT_DIR" \
  --json-out "$PROJECT_ROOT/validate_report.json"
```

6. Run high-risk scan:

```bash
python scripts/scan_subtitle_risks.py \
  "$PROJECT_ROOT" \
  --json-out "$PROJECT_ROOT/risk_report.json"
```

7. Run ASMR readability check:

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
- QC tier defaults to `--qc-tier two-pass`: first run full light QC with larger semantic chunks, then run focused deep QC on high-risk spans selected from translation flags, risk terms, long lines, residual Japanese/garbage text, and neighboring context. Use `--qc-tier standard` only for the old single-pass behavior, `light` for quick scans, and `deep` for focused reruns.
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
- Translation and QC default to existing local chat service ports when configured/available. For bulk translation, prefer non-reasoning instruct/chat models; Qwen3.x reasoning models require behavior probing before production use because hidden thinking tokens can make subtitle chunks extremely slow or cause blank responses.
- Windows/WSL default to Ollama for translation and QC when available.
- If Ollama is unavailable and `translate_backend=auto`, fall back to another available OpenAI-compatible backend.
- If the project explicitly sets `translate_backend=ollama`, missing Ollama is a blocker.
- macOS may continue using oMLX or another OpenAI-compatible local API.
- `check_environment.py` detects Python packages, scripts, external commands, ASR/backend availability, paths, output settings, and local API reachability.
- By default `check_environment.py` is read-only. With `--install-missing-python`, it may install small Python packages listed in its dependency table, such as `tqdm` and `PyYAML`, into the active interpreter.
- It must not silently install Ollama/oMLX, ASR backends, system packages, models, or start services; report those as user/agent setup actions.
- Translation and QC should use the selected local OpenAI-compatible chat service such as oMLX/Ollama/LM Studio.
- If local platform/local ASR API is unavailable and Python Whisper is unavailable in both the current interpreter and the shared user ASR venv, use `scripts/setup_whisper_backend.py` to install `openai-whisper` and download/cache the selected model after user approval.
- Local service ASR via `/audio/transcriptions` may be auto-selected only after `scripts/resolve_asr_route.py` verifies the endpoint. A chat-only endpoint must not be treated as ASR-capable.
- `asr_backend=auto` is not permission to install random ASR packages or guess local binaries; it is permission to probe known local platform ASR endpoints, then use the packaged Python Whisper route and its setup script if needed.

## Packaging Boundary

When preparing this as a formal Skill, include `SKILL.md`, `agents/`, `scripts/`, `references/`, `data/`, `docs/user_guide.md`, `docs/learning_library_guide.md`, `docs/channel_recovery.md`, and workflow/reference docs that the Skill directly links to. Exclude `generated_subtitles/`, `docs/implementation_log.md`, caches, local model files, private configs, and any per-work reports unless the user explicitly asks for a development snapshot.

## Finalization

Before final delivery:

1. Confirm structure validation has no errors.
2. Confirm high-risk findings are handled or explicitly recorded.
3. Confirm readability warnings are reviewed, especially high CPS and over-fragmentation.
4. Confirm mandatory QC is completed and clear issues are corrected.
5. At wrap-up, ask whether anything still needs correction and whether the user wants learning-library organization now. If the user asks for corrections, handle them and rerun affected checks before shared-corpus review. Work records can be drafted as part of delivery, but do not create review packets, queue entries, or migrations until the user chooses to organize/review learning-library items unless the user explicitly requested learning-library maintenance.
6. Run the learning loop before final response:
   - Read `docs/learning_library_guide.md` and classify every candidate lesson as `confirmed`, `project-only`, `pending`, or `false-positive`.
   - Extract reusable lessons from final subtitles, `qc_report.json`, risk findings, readability reports, and manual corrections.
   - Resolve write targets with `scripts/resolve_learning_paths.py`; Skill package `references/` and `data/subtitle_risk_patterns.json` are read-only during ordinary subtitle work.
   - Add a `$PROJECT_ROOT/learning/work_record.md` entry for every completed work, even when no new global rule is found.
   - If the user wants learning-library organization, ask whether this completed project should enter `agent-assisted shared corpus review`, be added to the review queue for `user-review`, or `skip shared corpus review`. Only after that choice, put reusable-looking findings into `$PROJECT_ROOT/learning/shared_corpus_review.md` and `shared_corpus_review.json`, and add the project to the user review queue. Do not promote them to the user long-term learning library unless the user explicitly approves specific items.
   - If the user chooses review, run `scripts/manage_shared_corpus_review.py "$PROJECT_ROOT" --choice <agent-assisted|user-review>` so future agents can find the pending review through `--list-queue`. If the user approves individual candidates, run `scripts/manage_shared_corpus_review.py --apply-approved --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"`.
   - Check the existing review buffer with `scripts/manage_shared_corpus_review.py --list-queue --json-out "$PROJECT_ROOT/learning/review_queue_status.json"` after the current project review choice is handled. If `pending_count` is greater than zero, tell the user how many pending review packets exist and ask whether they want agent help processing them now or prefer to defer.
   - After approval, extract reusable confirmed lessons into the user long-term learning library: durable terminology to `references/terms.md`, style/pacing rules to `references/style.md`, and easy-mistake/ASR-risk context or false-positive notes to `references/risk-notes.md`.
   - After approval, add mechanically scannable confirmed risks to the user long-term `data/subtitle_risk_patterns.local.json`.
   - Mark uncertain lessons in the project or user long-term `references/pending.md` instead of treating them as confirmed rules.
   - Use `scripts/update_learning_library.py` to draft or append the per-project learning record, then manually fill reusable lessons before delivery.
   - Do a learning self-check: if no shared reference was updated, explicitly record whether there were no reusable lessons, only project-specific lessons, only pending evidence, pending user review, or a user request not to globalize the lesson.
7. Convert/export according to `output_format`:
   - `vtt`: final `.zh.vtt`.
   - `srt`: final `.zh.srt`.
   - `both`: both `.zh.srt` and `.zh.vtt`.
   Use `scripts/export_final_subtitles.py "$ZH_SRT_DIR" "$FINAL_SUBTITLE_DIR" --format "$OUTPUT_FORMAT" --glob "*.zh.srt" --overwrite` for final export.
8. Export final subtitles to `$FINAL_SUBTITLE_DIR`, defaulting to `$SOURCE_PROJECT_DIR/subtitles/`, and keep that directory limited to final `.zh.vtt/.zh.srt` files.
9. Run `scripts/validate_subtitles.py --final-dir "$FINAL_SUBTITLE_DIR"` after export.

Report the final paths, output format, QC status, unresolved items, and a learning summary that names updated files, pending/project-only decisions, and the shared corpus review status.
