# Preflight Confirmation

开跑前必须完成 Preflight。它不是礼貌性询问，而是 ASR、翻译、QC 模型调用前的硬门禁。

## 必须先做的扫描

先解析项目上下文，再扫描音频 scope：

```bash
python scripts/resolve_project_context.py "/path/to/source_or_audio_root" --mkdir --json

python scripts/scan_audio_scope.py "$SOURCE_PROJECT_DIR" \
  --json-out "$PROJECT_ROOT/audio_scope_report.json"
```

如果本轮需要新 ASR，再扫描 ASR 音源版本：

```bash
python scripts/select_asr_audio_source.py "$SOURCE_PROJECT_DIR" \
  --json-out "$PROJECT_ROOT/audio_source_report.json"
```

`scan_audio_scope.py` 决定“哪些文件夹/音频进入本轮翻译范围”。`select_asr_audio_source.py` 决定“这些目标内容优先用哪个音源做 ASR”。无 SE 目录是 ASR 候选来源，不等于自动只翻无 SE 目录。

## 询问模板

向用户展示：

```text
我准备开始处理这个 ASMR。正式开跑前需要确认几个选项。

1. 本轮翻译范围
我在音声作品目录下发现这些音频文件夹：

[1] <folder> | <N> files | <duration or unknown> | <tags>
[2] <folder> | <N> files | <duration or unknown> | <tags>

请选择本轮要翻译哪些文件夹：
- 全部
- 指定编号/文件夹名
- 指定具体音频文件

说明：试听、DLC、EX、bonus、特典不会被默认歧视或跳过；但本轮必须由你确认范围。无 SE 文件夹只作为 ASR 来源优先候选，不代表只翻无 SE。

2. 精度模式
- draft：最快，适合先出粗稿
- standard：日常默认，dynamic chunk + two-pass QC
- premium：更慢，更小 chunk，更强 QC

建议：standard。

3. ASR
- 复用已有 .ja.asr.srt
- local platform /audio/transcriptions
- local-asr-api
- Python Whisper
- 受控 setup

建议：已有 ASR 时先复用；否则 large-v3。

4. 翻译模型
建议：本机可用时 qwen3.6-27b，通过配置的 OpenAI-compatible /chat/completions。

5. QC 模型
建议：standard 可用较快模型，premium 用强模型。无论第几轮 QC，都必须调用配置的 QC 模型，不用 agent 自审替代。

6. 输出格式
- vtt
- srt
- both

建议：vtt。

你可以直接回复类似：
“standard，翻 1 和 3，ASR 复用已有，翻译 27b，QC 27b，vtt”
```

## 落盘

用户确认后写入：

```bash
python scripts/prepare_run_profile.py "$PROJECT_ROOT" \
  --quality-mode standard \
  --scope selected_dirs \
  --selected-audio-dir "<folder>" \
  --output-format vtt \
  --asr-backend auto \
  --asr-model large-v3 \
  --reuse-existing-asr \
  --translate-backend auto \
  --translate-base-url "$TRANSLATE_BASE_URL" \
  --translate-model "$TRANSLATE_MODEL" \
  --qc-backend auto \
  --qc-base-url "$QC_BASE_URL" \
  --qc-model "$QC_MODEL" \
  --confirmed \
  --confirmation-source explicit_user \
  --confirmation-text "User confirmed scope, quality mode, ASR/translation/QC models, and output format." \
  --preflight-questions-presented \
  --audio-scope-report "$PROJECT_ROOT/audio_scope_report.json" \
  --overwrite
```

如果用户选择全部，使用 `--scope all`，并保留 `--audio-scope-report "$PROJECT_ROOT/audio_scope_report.json"` 或 `--audio-scope-summary "..."`。如果用户指定具体文件，使用 `--scope selected_files --selected-audio-file "<file>"`。如果用户明确说“全部按默认/你决定/不用问”，可以使用 `--confirmation-source user_default_authorized --confirmation-text "<用户授权原话或摘要>"`；auto mode 自身不算授权。

随后把本次确认的 stage 模型同步到用户可编辑的模型偏好：

```bash
python scripts/manage_model_profile.py sync-run-profile "$PROJECT_ROOT"
```

模型调用前必须检查：

```bash
python scripts/check_preflight.py "$PROJECT_ROOT" --stage asr
python scripts/check_preflight.py "$PROJECT_ROOT" --stage translate
python scripts/check_preflight.py "$PROJECT_ROOT" --stage qc
```

`check_preflight.py` 只确认本轮选择已经落盘；进入翻译或 QC 这种 chat 模型阶段前，还要确认当前本地后端真的能调用目标模型：

```bash
python scripts/prepare_model_stage.py "$PROJECT_ROOT" translate --previous-stage asr --from-config --api-key "$TRANSLATE_API_KEY"
python scripts/prepare_model_stage.py "$PROJECT_ROOT" qc --previous-stage translate --from-config --api-key "$TRANSLATE_API_KEY"
```

如果翻译模型和 QC 模型不同，QC 前的阶段检查是硬门禁。HTTP 500 常见原因是上一阶段模型尚未释放显存/内存、目标 QC 模型加载失败或过大、本地后端不支持自动热切换、模型名不匹配，或服务需要手动重载/重启。此时停止并让用户释放/切换/加载模型后重试，不要改用 agent 自身模型做 QC。

没有 confirmed `run_profile.json` 时，agent 必须停下询问。

## 质量模式参数

| mode | chunk preset | QC tier | 适用 |
| --- | --- | --- | --- |
| draft | turbo | off | 先出粗稿 |
| standard | fast | two-pass | 日常默认 |
| premium | safe | two-pass | 精品精修 |
| polish | safe | two-pass | 复用已有 ASR/翻译继续精修 |

`draft` 可以跳过完整模型 QC 和学习库更新，但仍必须保持 SRT 结构、编号、时间轴、覆盖率等质量底线。正式交付建议使用 `standard` 或 `premium`。
