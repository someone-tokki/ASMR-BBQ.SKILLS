# Platform Compatibility Notes

This project should keep subtitle checks, config records, and reports portable across macOS, Windows, and WSL. Platform-specific tools are implementation choices, not workflow contracts.

## Backend Defaults

- ASR backend defaults to `auto`, which means "probe local platform API `/audio/transcriptions` first, then configured `local-asr-api`, then packaged Python Whisper, then controlled setup"; it does not mean "install or try MLX". If Python `whisper` is missing and no local ASR API is reachable, use `setup_whisper_backend.py` as the controlled package/model setup route. Use `mlx_whisper` only when the user/project explicitly selects that route, such as `--asr-backend mlx_whisper` or `platform_profile=macos-mlx`.
- If a project already has usable `*.ja.asr.srt` files, missing local ASR packages should not block translation, QC, validation, or final export.
- Use `check_environment.py --require-asr` when the current run must create new ASR files.
- Before new ASR, run `resolve_asr_route.py`. In auto mode it resolves to `local-platform-asr-api` when a local platform endpoint supports `/audio/transcriptions`, to `local-asr-api` when a configured ASR endpoint is reachable, to `python-whisper` when the Python package is available, or to `setup_python_whisper_required` when setup is needed.
- Windows and WSL default to `ollama` for translation and QC when available.
- If `ollama` is not available, the agent should fall back to another available OpenAI-compatible backend, such as oMLX, LM Studio, a local server, or a user-approved cloud endpoint.
- macOS can continue using oMLX or another OpenAI-compatible local API by default. On this user's machine, translation/QC should prefer `qwen3.6-27b` when that model is available.
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
- Record ASR model and translation/QC model separately. Whisper/`large-v3` belongs to ASR; `qwen3.6-27b` is this user's preferred translation/QC chat model when available.
- Use explicit `--asr-backend mlx_whisper` only when the project should preserve or require the MLX route and the user accepts that backend/model setup.
- For Windows/WSL projects, `auto` should resolve to Ollama when `ollama` is installed.
- For Windows/WSL projects without Ollama, `auto` should recommend a fallback rather than failing the workflow at the config stage.
- Do not store API keys in `project_config.json`.
- Use relative paths in examples and reports when the file lives in the repository workspace.

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

`check_environment.py --install-missing-python` is only for lightweight workflow packages in the dependency table. Use `setup_whisper_backend.py` for openai-whisper package/model setup. It must not be used to install ASR engines such as `mlx_whisper` or to download arbitrary ASR models.

## Future One-Key Runner Behavior

When a one-key workflow entrypoint is added, it should follow this order:

1. Read `project_config.json`.
2. Run `check_environment.py`.
3. If existing `*.ja.asr.srt` files are present and valid, skip ASR backend blocking checks unless the user requested a new ASR run.
4. If `asr_backend=auto` and new ASR is required, route with `resolve_asr_route.py`: local platform ASR API, configured local ASR API, Python Whisper, then controlled setup. Do not assume MLX or guess a local ASR binary.
5. If `translate_backend=auto`, choose Ollama first on Windows/WSL.
6. If Ollama is unavailable, choose the next available OpenAI-compatible backend.
7. If no required backend is reachable, stop and report the missing service instead of guessing.
8. Never silently switch models after subtitles have already been generated for a project; record the backend/model change in the project notes. At each stage boundary, confirm the target interface and model: ASR uses `/audio/transcriptions` with a Whisper-class model; translation/QC uses `/chat/completions` with the configured chat model.
