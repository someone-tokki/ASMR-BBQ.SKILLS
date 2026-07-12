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

用户确认范围后，只有本轮需要新 ASR 时才运行：

```bash
python scripts/resolve_wav_only_asr_tracks.py \
  --audio-scope-report "$PROJECT_ROOT/audio_scope_report.json" \
  --audio-source-report "$PROJECT_ROOT/audio_source_report.json" \
  --scope selected_dirs \
  --selected-audio-dir "<folder>" \
  --json-out "$PROJECT_ROOT/wav_only_asr_report.json"
```

报告会先跨目录匹配同名且时长相符的原生 MP3。即使用户选择的是 WAV 目录作为翻译范围，只要没有明确指定 WAV 必须作为 ASR 音源，就自动用这个匹配 MP3 做 ASR；最终字幕仍映射回用户选择的曲目。`native_mp3_tracks` 保持直接作为 MP3 输入。只有匹配后仍为 `wav_only_choice_required=true` 时，才就 `wav_only_tracks` 追加提问；已有可用 `.ja.asr.srt` 的复用路线不运行该检查。

## 询问模板

向用户展示：

```text
我准备开始处理这个 ASMR。正式开跑前需要确认几个选项；请逐项回复。即使 ASR、翻译、QC 准备用同一个模型，也请分别写出三项，避免我擅自沿用模型。

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

4. ASR 音频准备（每次都必须显示结果）

- 若跨目录找到了安全、同轨且时长匹配的原生 MP3：明确告知“将直接用 `<MP3 track>` 做 ASR；不生成临时 MP3”。
- 若复用已有 `.ja.asr.srt`：明确告知“复用 ASR，本轮不需要音频准备”。
- 只有在跨目录匹配后仍检测到真正 WAV-only 的 ASR 轨道时，显示以下选择题：

本轮以下轨道只有 WAV，没有可安全使用的 MP3：

`<track list from wav_only_asr_report.json>`

是否只对这些轨道生成临时 16 kHz 双声道 MP3 缓存以加快 ASR？

- 转临时 MP3：只转换列出的 WAV-only 轨道；保留左右声道，成功后清理缓存。
- 直接使用 WAV：不做有损转换。

本篇或其他目录中已经有可靠、同轨且时长匹配的 MP3 时，会自动直接使用 MP3，并明确告知这一结果；不会询问 WAV 转码，也不会重新转换。

5. 翻译模型
建议：批量翻译优先使用非 reasoning instruct/chat 模型，例如 `Qwen2.5-32B-Instruct-GGUF-Q4_K_M` 或其他已验证的快速日译中模型。若用户选择 Qwen3.x/reasoning/未知模型，先跑行为探测确认 no-thinking、速度和 JSON 稳定性。

6. QC 模型
建议：standard 可用较快模型，premium 用强模型。无论第几轮 QC，都必须调用配置的 QC 模型，不用 agent 自审替代。

7. 输出格式
- vtt
- srt
- both

建议：vtt。

你可以直接回复类似：
“范围：翻 1 和 3；质量：standard；ASR：复用已有；翻译模型：27b；QC 模型：27b；输出：vtt；WAV-only：转临时 MP3”

只有检测到 WAV-only 轨道才需要最后一项；否则 agent 必须在开工问卷中明确写明“使用原生 MP3，无需临时转换”或“复用 ASR，音频准备不适用”。用户只回复部分项目时，保留已经确认的项目，明确列出其余未确认项目并停在这里；不得用推荐值补齐后开跑。
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
  --confirmed-item scope \
  --confirmed-item quality_mode \
  --confirmed-item asr \
  --confirmed-item translate \
  --confirmed-item qc \
  --confirmed-item output_format \
  --audio-scope-report "$PROJECT_ROOT/audio_scope_report.json" \
  --overwrite
```

如果用户选择全部，使用 `--scope all`，并保留 `--audio-scope-report "$PROJECT_ROOT/audio_scope_report.json"` 或 `--audio-scope-summary "..."`。如果用户指定具体文件，使用 `--scope selected_files --selected-audio-file "<file>"`。如果用户明确说“全部按默认/你决定/不用问”，可以使用 `--confirmation-source user_default_authorized --confirmation-text "<用户授权原话或摘要>"`；auto mode 自身不算授权。

若 `wav_only_asr_report.json` 显示 `wav_only_choice_required=true`，在上述命令中额外写入确认结果；二选一：

```bash
--wav-only-asr-required \
--wav-only-asr-strategy mp3_cache \
--wav-only-asr-report "$PROJECT_ROOT/wav_only_asr_report.json" \
--wav-only-asr-track "<wav-only track>"
```

同时加入：

```bash
--confirmed-item wav_only_asr_strategy
```

或：

```bash
--wav-only-asr-required \
--wav-only-asr-strategy original_wav \
--wav-only-asr-report "$PROJECT_ROOT/wav_only_asr_report.json" \
--wav-only-asr-track "<wav-only track>"
```

当选择 `mp3_cache` 时，只对报告列出的 WAV-only 文件逐个调用 `prepare_asr_audio_cache.py --normalize --normalize-format mp3`；生成的是临时 16 kHz 双声道 MP3，不能对已有 MP3 重转，也不能降混为单声道。

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

如果翻译模型是 Qwen3.x、reasoning 类、未知模型或新接入模型，翻译前还要跑行为探测：

```bash
python scripts/prepare_model_stage.py "$PROJECT_ROOT" translate --previous-stage asr --from-config --api-key "$TRANSLATE_API_KEY" --probe-behavior --require-non-thinking --json-out "$PROJECT_ROOT/model_stage_translate.json"
```

探测发现 hidden thinking、空响应、JSON 不稳定或短请求也明显超时，就停止并建议换非 reasoning instruct 模型，不要只靠调 chunk 硬跑。如果报告 `model_not_found`，先用 `/models` 里的精确 id 修正配置。如果报告 `model_load_failed`，或后端日志出现权重 shape / 架构不兼容，按模型/后端加载失败处理，不要误判为 no-thinking 限制导致所有 reasoning 模型不可用。如果普通请求可用、只有 no-thinking 请求失败，才归类为 `no_thinking_payload_rejected`。

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

如果本轮进入学习库更新，先按 `docs/learning_library_guide.md` 解析学习路径：项目记录写入 `$PROJECT_ROOT/learning/work_record.md`；收尾时若用户选择整理学习库，可复用经验先进入 shared corpus review，只有明确 approve 的条目才迁移到用户长期学习库 `${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/`。普通作品流程不要直接写已安装 Skill 包内的 `references/` 或 `data/subtitle_risk_patterns.json`。
