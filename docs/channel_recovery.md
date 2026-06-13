# 双声道补漏 ASR 说明

ASMR 中的双人或多人耳语常常不是普通的多人对话，而是一个声音偏左耳、一个声音偏右耳。混合音频直接 ASR 时，模型可能只识别较响的一侧，或把两侧台词混成一句。双声道补漏 ASR 用来处理这类场景。

## 原则

- 默认不要全片左右声道 ASR。大多数时间只有一个人说话，全片拆声道会浪费时间，并增加重复识别和 ASR 幻觉。
- 先跑主 ASR，主 ASR 仍是主要时间轴。
- 主 ASR 后可以默认跑轻量 channel activity scan，只生成候选报告，不切全片、不合并字幕。
- 检测不只看主 ASR 空白，也会把弱覆盖当候选信号：例如主 ASR 只有 `……`、`...`、极短喘息/拟声、触发音、或长时间音频只对应极短文本。
- 只对候选片段做 channel recovery：用户指出的时间段、主 ASR 长空白或弱覆盖但音频有声、QC/抽听发现漏字幕、或疑似双人左右耳语片段。
- 左右声道结果先作为候选材料，不自动覆盖主 `.ja.asr.srt`，也不直接进入翻译输出。
- 接受补漏前必须对照主 ASR、相邻字幕、音轨标题、必要时抽听或用户反馈。
- 亲吻、舔耳、喘息、摩擦等非语言音效可能在单声道 ASR 中被幻觉成台词；这类结果默认谨慎处理。
- 如果检测报告标记 `needs_user_disambiguation` 或 `user_disambiguation_required`，agent 必须明确提醒用户甄别：这段可能是有效台词，也可能只是 ASMR 音效/BGM/喘息。

## 产物位置

建议放在：

```text
$PROJECT_ROOT/channel_recovery/<track_stem>/
  channel_recovery_manifest.json
  channel_recovery_review.md
  clips/
    <track>__w001__...__left.wav
    <track>__w001__...__right.wav
  asr/
    <clip>.ja.asr.json
    <clip>.ja.asr.srt
```

这些都是工程/审阅产物，不应进入最终字幕目录。

## 准备候选窗口

主 ASR 完成后，可先跑轻量左右声道活动检测。它基于左右声道能量、声道差异、主 ASR 空白和主 ASR 弱覆盖情况生成候选，不证明一定有人声：

```bash
python scripts/detect_channel_activity.py \
  "$AUDIO_FILE" \
  --main-asr "$ASR_DIR/$TRACK_STEM.ja.asr.srt" \
  --json-out "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/channel_activity_candidates.json"
```

报告中的 `high` 候选可以考虑进入补漏准备；`medium` / `low` 或带 `needs_user_disambiguation` 的候选必须先提醒用户或抽听甄别。

如需让检测脚本直接准备高置信候选 clip：

```bash
python scripts/detect_channel_activity.py \
  "$AUDIO_FILE" \
  --main-asr "$ASR_DIR/$TRACK_STEM.ja.asr.srt" \
  --json-out "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/channel_activity_candidates.json" \
  --prepare-out "$PROJECT_ROOT/channel_recovery/$TRACK_STEM" \
  --prepare-min-confidence high
```

用户明确指定时间段时：

```bash
python scripts/prepare_channel_recovery.py \
  "$AUDIO_FILE" \
  --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM" \
  --window 03:12-03:28 \
  --window 07:40-07:55
```

从主 ASR 的长空白段自动生成候选窗口：

```bash
python scripts/prepare_channel_recovery.py \
  "$AUDIO_FILE" \
  --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM" \
  --from-srt "$ASR_DIR/$TRACK_STEM.ja.asr.srt" \
  --min-gap 2.0 \
  --pad 0.25
```

该脚本只切左右声道 clip、生成 manifest 和 review 模板，不调用 ASR，不修改主字幕。

## 对左右声道 clip 跑 ASR

继续使用当前项目解析出的 ASR backend/model。若本地平台支持 `/audio/transcriptions`：

```bash
python scripts/transcribe_openai_audio.py \
  "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/clips" \
  --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/asr" \
  --base-url "$ASR_BASE_URL" \
  --model "$ASR_MODEL" \
  --glob "*.wav"
```

若走 Python Whisper：

```bash
python scripts/transcribe_whisper.py \
  "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/clips" \
  --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/asr" \
  --model "$ASR_MODEL" \
  --glob "*.wav"
```

## 审阅和合并

`channel_recovery_review.md` 用来记录每个窗口的决定：

- `accept-left`：只接受左声道。
- `accept-right`：只接受右声道。
- `accept-both`：左右声道都有有效台词。
- `reject`：重复、噪声、幻觉或无法确认。
- `pending`：证据不足，等待用户或抽听确认。

只有明确缺失的台词才应并入主 ASR/中文字幕。合并时要保留原主字幕编号和时间轴质量要求；如果需要新增字幕条目，必须先说明这是 ASR 时间轴修复，不属于普通翻译阶段，并重新跑结构校验、翻译、QC 和导出。

当检测不确定时，最终或阶段汇报必须写清：

```text
检测到疑似左右声道活动，但无法确认是否为台词。请用户或抽听甄别后再决定是否转写/合并。
```

如果主 ASR 有输出但只有省略号、极短拟声或触发音，也要提醒：

```text
主 ASR 有输出，但内容疑似只是省略号/拟声/触发音，不足以排除漏台词。请甄别是否需要双声道补漏。
```

## 翻译格式建议

如果左右声道同时有不同有效台词，翻译前应保留结构，不要把左右文字混成一句。建议：

```text
【左】别动哦……
【右】我在这边亲你。
```

或在中间审阅 JSON 中保留：

```json
{
  "speakers": [
    {"channel": "L", "ja": "...", "zh": "..."},
    {"channel": "R", "ja": "...", "zh": "..."}
  ]
}
```

最终显示可以是同一字幕块内两行，但翻译/QC 时必须知道哪一行来自哪个声道，避免互相污染。
