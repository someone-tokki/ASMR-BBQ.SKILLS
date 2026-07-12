# Platform Compatibility Notes

This project should keep subtitle checks, config records, and reports portable across macOS, Windows, and WSL. Platform-specific tools are implementation choices, not workflow contracts.

## Backend Defaults

- ASR backend defaults to `auto`, which means "probe local platform API `/audio/transcriptions` first, then configured `local-asr-api`, then packaged Python Whisper, then controlled setup"; it does not mean "install or try MLX". If Python `whisper` is missing and no local ASR API is reachable, use `setup_whisper_backend.py` as the controlled package/model setup route. Use `mlx_whisper` only when the user/project explicitly selects that route, such as `--asr-backend mlx_whisper` or `platform_profile=macos-mlx`.
- `setup_whisper_backend.py` installs openai-whisper into the shared user ASR venv by default: `${ASMR_SUBTITLE_ASR_DIR:-~/ASMR-Subtitle-Translator/asr}/openai-whisper-venv`. Same-machine agents should reuse that venv instead of repeatedly installing Whisper into each active Python interpreter. Use `--no-shared` only when the user explicitly wants interpreter-local setup.
- If a project already has usable `*.ja.asr.srt` files, missing local ASR packages should not block translation, QC, validation, or final export.
- Use `check_environment.py --require-asr` when the current run must create new ASR files.
- Before new ASR, run `resolve_asr_route.py`. In auto mode it resolves to `local-platform-asr-api` when a local platform endpoint supports `/audio/transcriptions`, to `local-asr-api` when a configured ASR endpoint is reachable, to `python-whisper` when the Python package is available, or to `setup_python_whisper_required` when setup is needed.
- ASR optimizations such as VAD, overlap/stride, segment-level resume, and previous-transcript prompts are backend capabilities, not mandatory assumptions. Use them when the selected ASR tool supports them; otherwise record that they were not used. Do not install or swap ASR engines solely to obtain these options without user approval.
- Windows and WSL default to `ollama` for translation and QC when available.
- If `ollama` is not available, the agent should fall back to another available OpenAI-compatible backend, such as oMLX, LM Studio, a local server, or a user-approved cloud endpoint.
- macOS can continue using oMLX or another OpenAI-compatible local API by default. For bulk subtitle translation, prefer a non-reasoning instruct/chat model such as `Qwen2.5-32B-Instruct-GGUF-Q4_K_M` or another verified fast Japanese/Chinese model. Qwen3.x reasoning models must pass behavior probing before production use.
- `translate_backend=auto` means the environment check recommends the backend; it does not start services by itself.
- If `translate_backend` is explicitly set to `ollama`, missing Ollama is a blocker.
- If `translate_backend` is explicitly set to another backend, that explicit project choice overrides the platform default.

## Recommended Profiles

| Profile | ASR direction | Translation/QC direction | Notes |
| --- | --- | --- | --- |
| macOS Apple Silicon | Local platform `/audio/transcriptions`, then Python Whisper; explicit MLX only when selected | oMLX or OpenAI-compatible local API | Existing MLX route remains valid only when selected; auto should not install/download MLX outside setup script. |
| Windows | Local platform `/audio/transcriptions`, then Python Whisper | Ollama first, fallback to OpenAI-compatible | Avoid MLX-only assumptions. |
| WSL | Local platform `/audio/transcriptions`, then Python Whisper | Ollama first, fallback to OpenAI-compatible | Keep paths relative where possible. |
| Generic Linux | Local platform `/audio/transcriptions`, then Python Whisper | OpenAI-compatible backend | Ollama may still be used if installed. |

## Configuration Rules

- Prefer `--translate-backend auto` in new `project_config.json` records unless the user has already chosen a concrete backend.
- Prefer `--asr-backend auto` and `--asr-model "$ASR_MODEL"` in new `project_config.json` records unless the user has already chosen a concrete ASR backend.
- Record ASR model and translation/QC model separately. Whisper/`large-v3` belongs to ASR; bulk translation should prefer a non-reasoning instruct/chat model. Reasoning models may be used only after behavior probing confirms no hidden-thinking latency, blank response, or JSON instability. A reasoning model returning HTTP 500 on both plain and no-thinking minimal chat probes is a backend/model loading failure; check exact model id, memory, model conversion, architecture support, and backend logs before changing subtitle chunking or prompt rules.
- Use `$PROJECT_ROOT/model_profile.json` for user-editable stage model preferences when ASR, translation, and QC should use different models, base URLs, or backends. Resolve it with `scripts/manage_model_profile.py resolve "$PROJECT_ROOT" <stage> --from-config` before each stage.
- `model_profile.json` is not a secrets file and does not start services, install packages, unload models, or download models. It only records preferences for the agent to apply.
- Stage model choices are binding for workflow steps. Translation, mandatory QC, and optional QC refinement must call the resolved local/configured `/chat/completions` endpoint through the workflow scripts. If the configured service is missing, it is a setup/backend problem; it is not permission for the agent to use its own model as a hidden replacement QC model.
- Before translation, mandatory QC, or additional QC refinement, run `scripts/prepare_model_stage.py "$PROJECT_ROOT" <translate|qc> --previous-stage <stage> --from-config` to verify the target chat model can answer now. This check is separate from Preflight: Preflight records intended model choices, while stage preparation checks the current live backend state.
- If translation and QC use different models, the QC stage check is mandatory. A local HTTP 500 during the check or QC call often means the previous translation model is still occupying memory, the QC model failed to load or is too large, the backend cannot hot-switch models, the model id is wrong, or the service needs a manual reload/restart. If `/models` exposes a similar but longer id, use that exact id. If both a plain minimal chat request and the Skill no-thinking request fail with 5xx, diagnose model/backend loading rather than assuming no-thinking controls are the cause. Stop and ask the user to release/unload/switch models, then rerun the stage check; do not substitute the agent's own model.
- Use explicit `--asr-backend mlx_whisper` only when the project should preserve or require the MLX route and the user accepts that backend/model setup.
- For Windows/WSL projects, `auto` should resolve to Ollama when `ollama` is installed.
- For Windows/WSL projects without Ollama, `auto` should recommend a fallback rather than failing the workflow at the config stage.
- Do not store API keys in `project_config.json`.
- Use relative paths in examples and reports when the file lives in the repository workspace.
- `ffprobe` improves cross-format duration matching but is not required merely to avoid a redundant WAV transcode. If it is unavailable on Windows or macOS, `resolve_wav_only_asr_tracks.py` may use a same normalized track name plus non-preview/non-tiny native MP3 as a conservative fallback; the report must label this as `name_match_duration_unavailable`. A duration mismatch remains unsafe and must not be auto-selected.

## Learning Paths

- Skill package references are portable defaults: `references/` and `data/subtitle_risk_patterns.json` are read-only during ordinary subtitle work.
- Resolve per-run learning targets with `scripts/resolve_learning_paths.py "$PROJECT_ROOT"` before writing learning records. The resolver reports the built-in reference directory, the user long-term learning directory, and `$PROJECT_ROOT/learning/`.
- Project-specific lessons, pending notes, imported stray reference files, and promotion drafts belong under `$PROJECT_ROOT/learning/` so they travel with the subtitle project.
- Confirmed reusable lessons belong in the user long-term learning library under `${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/`, not in the installed Skill package.
- Mechanically scannable confirmed user rules should use the user long-term `data/subtitle_risk_patterns.local.json`; the built-in `data/subtitle_risk_patterns.json` remains the packaged default rule set.

## Environment Check

Run:

```bash
python scripts/check_environment.py \
  --config "$PROJECT_ROOT/project_config.json" \
  --json-out "$PROJECT_ROOT/env_report.json"
```

The report should be read as:

- `FAIL`: the current configured route cannot run, such as a missing required Python dependency, missing required script, invalid config, or explicitly required backend command.
- `WARN`: useful tool or preferred backend is missing, but a fallback route may still work.
- `OK`: detected and ready for the checked route.

By default, `check_environment.py` is read-only. To preview missing lightweight Python packages, run:

```bash
python scripts/check_environment.py --dry-run-install --skip-api
```

When dependency changes are allowed, it can install missing Python packages into the active interpreter:

```bash
python scripts/check_environment.py --install-missing-python --skip-api
```

It still must not silently install Ollama, oMLX, ASR backends, system packages, or models, and it must not start services. Report those as user/agent setup actions.

`check_environment.py --install-missing-python` is only for lightweight workflow packages in the dependency table. Use `setup_whisper_backend.py` for openai-whisper package/model setup; it targets the shared user ASR venv by default. It must not be used to install ASR engines such as `mlx_whisper` or to download arbitrary ASR models.

## Future One-Key Runner Behavior

When a one-key workflow entrypoint is added, it should follow this order:

1. Read `project_config.json` and `model_profile.json` when present.
2. Run `check_environment.py`.
3. If existing `*.ja.asr.srt` files are present and valid, skip ASR backend blocking checks unless the user requested a new ASR run.
4. If `asr_backend=auto` and new ASR is required, route with `resolve_asr_route.py`: local platform ASR API, configured local ASR API, Python Whisper, then controlled setup. Do not assume MLX or guess a local ASR binary.
5. If `translate_backend=auto`, choose Ollama first on Windows/WSL.
6. If Ollama is unavailable, choose the next available OpenAI-compatible backend.
7. If no required backend is reachable, stop and report the missing service instead of guessing.
8. Never silently switch models after subtitles have already been generated for a project; record the backend/model change in the project notes or `model_profile.json`. At each stage boundary, confirm the target interface and model: ASR uses `/audio/transcriptions` with a Whisper-class model; translation/QC uses `/chat/completions` with the configured chat model. Use `prepare_model_stage.py` before chat model stages, especially when moving from a translation model to a different QC model. Second and later QC refinement rounds follow the same rule.
