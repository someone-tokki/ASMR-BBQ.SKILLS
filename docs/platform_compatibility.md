# Platform Compatibility Notes

This project should keep subtitle checks, config records, and reports portable across macOS, Windows, and WSL. Platform-specific tools are implementation choices, not workflow contracts.

## Backend Defaults

- ASR backend defaults to `auto`. macOS may use `mlx_whisper` when available; Windows/WSL should avoid MLX-only assumptions and use an available Whisper-compatible or external ASR route.
- If a project already has usable `*.ja.asr.srt` files, missing local ASR packages should not block translation, QC, validation, or final export.
- Use `check_environment.py --require-asr` when the current run must create new ASR files.
- Windows and WSL default to `ollama` for translation and QC when available.
- If `ollama` is not available, the agent should fall back to another available OpenAI-compatible backend, such as oMLX, LM Studio, a local server, or a user-approved cloud endpoint.
- macOS can continue using oMLX or another OpenAI-compatible local API by default.
- `translate_backend=auto` means the environment check recommends the backend; it does not start services by itself.
- If `translate_backend` is explicitly set to `ollama`, missing Ollama is a blocker.
- If `translate_backend` is explicitly set to another backend, that explicit project choice overrides the platform default.

## Recommended Profiles

| Profile | ASR direction | Translation/QC direction | Notes |
| --- | --- | --- | --- |
| macOS Apple Silicon | `mlx_whisper` if available | oMLX or OpenAI-compatible local API | Existing MLX route remains valid. |
| Windows | Faster/stronger available Whisper-compatible ASR | Ollama first, fallback to OpenAI-compatible | Avoid MLX-only assumptions. |
| WSL | Linux-compatible Whisper/ASR path | Ollama first, fallback to OpenAI-compatible | Keep paths relative where possible. |
| Generic Linux | Available Whisper/ASR path | OpenAI-compatible backend | Ollama may still be used if installed. |

## Configuration Rules

- Prefer `--translate-backend auto` in new `project_config.json` records unless the user has already chosen a concrete backend.
- Prefer `--asr-backend auto` in new `project_config.json` records unless the user has already chosen a concrete ASR backend.
- Use explicit `--asr-backend mlx_whisper` only when the project should preserve or require the MLX route.
- For Windows/WSL projects, `auto` should resolve to Ollama when `ollama` is installed.
- For Windows/WSL projects without Ollama, `auto` should recommend a fallback rather than failing the workflow at the config stage.
- Do not store API keys in `project_config.json`.
- Use relative paths in examples and reports when the file lives in the repository workspace.

## Environment Check

Run:

```bash
python tools/check_environment.py \
  --config "generated_subtitles/<work_id>/project_config.json" \
  --json-out "generated_subtitles/<work_id>/env_report.json"
```

The report should be read as:

- `FAIL`: the current configured route cannot run, such as a missing required Python dependency, missing required script, invalid config, or explicitly required backend command.
- `WARN`: useful tool or preferred backend is missing, but a fallback route may still work.
- `OK`: detected and ready for the checked route.

`check_environment.py` is read-only. It recommends backend selection but does not install packages, start Ollama, start oMLX, or download models.

## Future One-Key Runner Behavior

When a one-key workflow entrypoint is added, it should follow this order:

1. Read `project_config.json`.
2. Run `check_environment.py`.
3. If existing `*.ja.asr.srt` files are present and valid, skip ASR backend blocking checks unless the user requested a new ASR run.
4. If `asr_backend=auto` and new ASR is required, choose the best available ASR route for the platform; do not assume MLX on Windows/WSL.
5. If `translate_backend=auto`, choose Ollama first on Windows/WSL.
6. If Ollama is unavailable, choose the next available OpenAI-compatible backend.
7. If no required backend is reachable, stop and report the missing service instead of guessing.
8. Never silently switch models after subtitles have already been generated for a project; record the backend/model change in the project notes.
