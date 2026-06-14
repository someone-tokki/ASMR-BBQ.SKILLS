# 无对照台本的 ASMR 烤肉工作流

适用场景：作品只有音频，没有官方台本、初稿台本或可用文本。目标仍是为每条音频生成独立、可挂载、自然可读的简体中文字幕。

开始前必须用 `docs/task_routing.md` 确认属于无台本路线，再阅读 `docs/asmr_translation_corpus.md` 索引，并按需要加载 `references/style.md`、`references/terms.md` 和 `references/risk-notes.md`。完成后先把新发现的术语、错词和风格规则写入项目 work record，并注明“无台本验证”；收尾时询问用户是否要修正或整理学习库，只有明确 approve 的条目才迁移到 shared corpus。

## 核心原则

- 无台本时，ASR 是字幕时间轴和原文的主要来源，但不能盲信。
- 使用当前可用的较好 ASR 方案和更严格的人工校对；模型可替换。
- 不能确认的句子要标为待复核或向用户说明，不要编剧情。
- 促销/试听、EX/free talk、bonus、DLC、特典等附加音频也要单独跑、单独校对；开跑前必须先列出音频文件夹并让用户确认本轮范围，不能默认歧视或跳过附加音频。
- 中文质量目标与有台本项目相同：自然、有人情味、符合情境，不生硬直译。
- 所有优化都不能破坏质量底线：保持 SRT 编号、顺序、开始时间、结束时间不变；翻译输出必须覆盖所有目标编号；context halo 只用于理解，不能写入输出；QC 建议只能作为候选，不能直接自动改字幕；ASMR 语义、角色关系、动作连续性优先于机械压缩 chunk；缓存命中不能复用到内容、模型、prompt/schema、参数或上下文不一致的 chunk。
- 长时间 ASR/翻译任务应使用脚本侧进度条；正常推进时少打扰用户，只有报错、需要决策或阶段完成时再单独说明。
- 模型质检是必经步骤，不是可选项。无台本项目尤其容易出现“单句看似通顺、整段逻辑跑偏”的错译，必须用模型对照日文 ASR 和中文字幕做一轮候选问题扫描。

如果使用第三方平台或本地推理服务，比如 Ollama、oMLX、LM Studio 或类似工具，优先走它们官方提供的调用接口。若该平台提供的是 OpenAI-compatible API，就优先直接调用这套接口，而不是通过间接包装、非官方桥接或界面自动化去调用。Windows/WSL 默认优先 Ollama；没有 Ollama 时，agent 应按环境检测结果回退到其他可用 OpenAI-compatible 后端。端口也优先采用平台官方默认端口；只有在默认端口被占用、服务不可用或平台明确要求时，才改用其他端口。这样更容易观察模型运行状态，也更方便看端口、请求和日志，出了问题时能更快判断是模型、服务还是脚本本身。跨平台规则见 [platform_compatibility.md](platform_compatibility.md)。

## 推荐输出结构

```text
$SOURCE_PROJECT_DIR/  # 源 ASMR 作品根目录
  subtitle_project/  # 默认 PROJECT_ROOT，工程文件和中间文件集中放这里
    project_config.json
    env_report.json
    audio_source_report.json
    asr_route_report.json
    <asr_dir>/
      <track>.ja.asr.json
      <track>.ja.asr.srt
    srt_work/
      <track>.zh.srt
    <promo_asr_dir>/
      <promo>.ja.asr.json
      <promo>.ja.asr.srt
    promo_srt_work/
      <promo>.zh.srt
    qc_report.json
    qc_report_chunks/
    qc_refinement/
    channel_recovery/
      <track>/
        channel_recovery_manifest.json
        channel_recovery_review.md
        clips/
        asr/
    review_notes.md
  subtitles/  # 默认 FINAL_SUBTITLE_DIR，只放最终交付字幕
    <track>.zh.vtt
    <promo>.zh.vtt

$PROJECT_ROOT/  # 默认等于 $SOURCE_PROJECT_DIR/subtitle_project/
  <asr_dir>/
    <track>.ja.asr.json
    <track>.ja.asr.srt
  srt_work/
    <track>.zh.srt
  <promo_asr_dir>/
    <promo>.ja.asr.json
    <promo>.ja.asr.srt
  promo_srt_work/
    <promo>.zh.srt
  channel_recovery/
    <track>/
      clips/
      asr/
  review_notes.md

$FINAL_SUBTITLE_DIR/  # 默认是 $SOURCE_PROJECT_DIR/subtitles/
  <track>.zh.vtt      # 默认最终格式；用户可要求 .zh.srt 或 both
  <promo>.zh.vtt
```

`$SOURCE_PROJECT_DIR` 默认是源 ASMR 作品根目录；`$PROJECT_ROOT` 默认是 `$SOURCE_PROJECT_DIR/subtitle_project/`，不再默认创建 `generated_subtitles/<WORK_ID>`，也不要把 `project_config.json`、QC 报告、ASR 中间稿等散放在作品根目录。ASR、SRT 中间稿、QC 报告、review notes、学习库草稿等工作产物放在 `$PROJECT_ROOT` 下的专用子目录/文件。最终字幕统一放进 `$FINAL_SUBTITLE_DIR`，默认是 `$SOURCE_PROJECT_DIR/subtitles/`；不要再按 `音声/`、`WAV 本編/`、`プロモーション用音声/` 等音频目录创建同名成品目录。默认最终字幕为 `.zh.vtt`；用户指定 `srt` 或 `both` 时，可放 `.zh.srt` 或两种格式。本篇、EX、促销/试听字幕都可以放在同一个 `$FINAL_SUBTITLE_DIR`，用保留来源轨道 stem 的文件名区分，避免覆盖。

DLsite 音声自带字幕常见格式是 WebVTT。默认最终导出格式按 `.vtt` 处理；如果用户明确要求 `srt` 或 `both`，按用户选择交付。`.zh.srt` 默认仍作为 ASR、翻译、校验和手修阶段的中间格式保留。

## 执行步骤

0. Preflight 开烤确认

   在任何 ASR、翻译或 QC 模型调用前，必须先完成 Preflight。先解析项目上下文并扫描音频文件夹：

   ```bash
   python scripts/resolve_project_context.py "/path/to/source_or_audio_root" --mkdir --json

   python scripts/scan_audio_scope.py "$SOURCE_PROJECT_DIR" \
     --json-out "$PROJECT_ROOT/audio_scope_report.json"
   ```

   向用户展示 `audio_scope_report.json` 中的文件夹清单，询问本轮要翻译哪些音频文件夹或具体文件。试听、DLC、EX、bonus、特典不能被默认排除；只有用户确认 `all` 时才全量处理。无 SE 目录只作为 ASR 来源优先候选，不等于自动只翻无 SE。

   同时确认质量模式、ASR/翻译/QC 模型和输出格式。用户确认后写入本次运行记录：

   ```bash
   python scripts/prepare_run_profile.py "$PROJECT_ROOT" \
     --quality-mode standard \
     --scope selected_dirs \
     --selected-audio-dir "<folder-from-audio-scope-report>" \
     --output-format vtt \
     --asr-backend auto \
     --asr-model large-v3 \
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

   如果用户选择全部，用 `--scope all` 并保留音频扫描报告；如果指定具体音频，用 `--scope selected_files --selected-audio-file "<file>"`。auto mode 不等于用户确认；只有用户明确说“全部按默认/你决定/不用问”时，才可改用 `--confirmation-source user_default_authorized --confirmation-text "<用户授权原话或摘要>"`。后续每个模型阶段前都要硬检查：

   ```bash
   python scripts/check_preflight.py "$PROJECT_ROOT" --stage asr
   python scripts/check_preflight.py "$PROJECT_ROOT" --stage translate
   python scripts/check_preflight.py "$PROJECT_ROOT" --stage qc
   ```

   质量模式映射：`draft -> turbo` 粗烤，`standard -> fast + two-pass QC`，`premium -> safe + two-pass QC`，`polish -> safe + two-pass QC`。

1. 盘点音频和元信息

   先解析项目上下文。这个步骤必须在创建配置或写任何输出文件前完成；如果源目录或父目录名是 `RJxxxx`，脚本会把它识别为 `WORK_ID`：

   ```bash
   python scripts/resolve_project_context.py "/path/to/source_or_audio_root" --mkdir --json
   ```

   后续命令使用返回的 `PROJECT_ROOT`、`SOURCE_PROJECT_DIR`、`FINAL_SUBTITLE_DIR`。默认 `PROJECT_ROOT` 是 `$SOURCE_PROJECT_DIR/subtitle_project/`，只用于工程文件和中间文件；默认 `FINAL_SUBTITLE_DIR` 是 `$SOURCE_PROJECT_DIR/subtitles/`，只用于最终 `.zh.vtt/.zh.srt` 交付。不要创建额外的 `generated_subtitles/<WORK_ID>`，除非用户显式指定 `--output-root` 或 `--project-root`。

   - 递归列出源作品文件夹下所有目标音频文件、标题、时长、目录结构。
   - 根据文件名判断剧情顺序、本篇、EX/free talk、bonus、DLC、特典、促销/试听，但分类只用于组织工作目录和命名，不用于默认排除。
   - 不要只看主线编号、目录名或“看起来是试听/附赠”就跳过音频。实际处理范围以 Preflight 中用户确认的文件夹或文件为准。
   - 若有 DLsite 商品页文本、标题、角色介绍、试听说明，可作为低强度上下文参考，但不要当完整台本。
   - 如果目录名或用户输入中识别到 RJ 号，且允许联网，可抓取 DLsite 商品页元信息：

   ```bash
   python scripts/fetch_dlsite_work_info.py "RJxxxx" \
     --out "$PROJECT_ROOT/dlsite_work_info.json" \
     --allow-fail
   ```

   抓取失败不阻塞流程；成功时，标题、社团、标签和简介只作为低强度上下文。

   如果音频包里可能同时有有 SE/无 SE 版本，先做 ASR 音源选择扫描：

   ```bash
   python scripts/select_asr_audio_source.py "/path/to/audio_root" \
     --json-out "$PROJECT_ROOT/audio_source_report.json"
   ```

   默认按扫描报告的 `recommended_asr_files` 选择 ASR 输入：用户明确指定有 SE、通常版或某个目录/文件时，以用户指定为准，并可用 `--user-selected "/path/to/user_choice"` 记录该覆盖选择；否则只有在无 SE 文件能和普通音频按轨道名对齐且 `requires_review=false` 时，才默认使用这些无 SE 文件。无 SE 同一轨道同时有 MP3/WAV 时，优先选 MP3 以加快 ASR；若报告出现未匹配、疑似试听/裁剪/占位文件等 warning 或 `requires_review=true`，先人工核对时长和轨道对应关系。

2. 读取语料库

   - 先读 `docs/asmr_translation_corpus.md` 索引。
   - 翻译前读 `references/style.md` 和 `references/terms.md`。
   - QC 和扫雷前读 `references/risk-notes.md`。
   - 记录本作初始术语：角色称呼、关系、场景、性行为词、音效偏好。

3. 建立项目配置记录

   开工后尽早创建或更新 `$PROJECT_ROOT/project_config.json`。配置只记录当前项目的目录、模型、输出格式和报告路径，不自动驱动流程；agent 和分阶段工具会读取它作为复现记录。

   ```bash
   export LOCAL_MODEL_BASE_URL="http://127.0.0.1:8000/v1"  # 本地平台 API；LM Studio 常用 1234，Ollama 常用 11434
   export ASR_MODEL="large-v3"
   export TRANSLATE_BASE_URL="$LOCAL_MODEL_BASE_URL"
   export TRANSLATE_MODEL="${TRANSLATE_MODEL:-Qwen2.5-32B-Instruct-GGUF-Q4_K_M}"  # 本机默认推荐；若 /models 中名称不同，用实际 model id
   export QC_BASE_URL="${QC_BASE_URL:-$TRANSLATE_BASE_URL}"
   export QC_MODEL="${QC_MODEL:-$TRANSLATE_MODEL}"

   python scripts/manage_project_config.py init "$PROJECT_ROOT" \
     --work-id "$WORK_ID" \
     --project-type no-script \
     --source-audio-dir "$SOURCE_AUDIO_DIR" \
     --asr-dir "$PROJECT_ROOT/<asr_dir>" \
     --zh-srt-dir "$PROJECT_ROOT/srt_work" \
     --final-dir "$FINAL_SUBTITLE_DIR" \
     --asr-model "$ASR_MODEL" \
     --asr-backend auto \
     --output-format vtt \
     --translate-backend auto \
     --translate-base-url "$TRANSLATE_BASE_URL" \
     --translate-model "$TRANSLATE_MODEL" \
     --qc-backend auto \
     --qc-base-url "$QC_BASE_URL" \
     --qc-model "$QC_MODEL" \
     --overwrite
   ```

   同时创建用户可编辑的工况模型偏好文件。这个文件不是密钥配置，不写 API key；用户可以用它指定 ASR、翻译、QC 分别使用什么 backend/base URL/model：

   ```bash
   python scripts/manage_model_profile.py init "$PROJECT_ROOT" --from-config --overwrite
   ```

   如果用户在任务中要求不同工况使用不同模型，用 `set-stage` 写入偏好。例如：

   ```bash
   python scripts/manage_model_profile.py set-stage "$PROJECT_ROOT" asr \
     --backend auto \
     --model large-v3 \
     --interface /audio/transcriptions

   python scripts/manage_model_profile.py set-stage "$PROJECT_ROOT" translate \
     --backend auto \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --interface /chat/completions

   python scripts/manage_model_profile.py set-stage "$PROJECT_ROOT" qc \
     --backend auto \
     --base-url "$QC_BASE_URL" \
     --model "$QC_MODEL" \
     --interface /chat/completions
   ```

   每个阶段开始前先 resolve 当前有效选择；agent 后续命令应使用 resolve 结果，而不是把上一阶段模型沿用到下一阶段：

   ```bash
   python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" asr --from-config
   python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" translate --from-config
   python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" qc --from-config
   ```

   可随时查看配置摘要：

   ```bash
   python scripts/manage_project_config.py show "$PROJECT_ROOT"
   ```

   随后跑一次环境检测，确认脚本、Python 依赖、项目路径、ASR/翻译后端、外部命令和本地翻译 API 状态。默认只报告；如果缺轻量 Python 包，可先 dry-run，再在用户允许时自动安装。API 服务尚未启动时通常只会得到 warning；已有 `.ja.asr.srt` 时，本地 ASR 后端缺失通常不应阻塞翻译/QC/校验；如果本轮需要新跑 ASR，加 `--require-asr` 做更严格检查。

   ```bash
   python scripts/check_environment.py \
     --config "$PROJECT_ROOT/project_config.json" \
     --json-out "$PROJECT_ROOT/env_report.json"
   ```

   如报告缺少 `tqdm`、`PyYAML` 等轻量 Python 包，可先预览安装命令：

   ```bash
   python scripts/check_environment.py --dry-run-install --skip-api
   ```

   用户允许修改当前 Python 环境时再安装：

   ```bash
   python scripts/check_environment.py --install-missing-python --skip-api
   ```

4. 使用高质量 ASR

   若 `project_config.json` 指向的 ASR 目录已经有可用的 `*.ja.asr.srt`，且结构校验通过，可以跳过本步骤，直接进入 ASR 自检或翻译。只有需要新跑 ASR 时，才必须先跑 ASR 路线分流：

   ```bash
   python scripts/resolve_asr_route.py \
     --config "$PROJECT_ROOT/project_config.json" \
     --require-new-asr \
     --json-out "$PROJECT_ROOT/asr_route_report.json"
   ```

   默认 ASR 路线不是直接假定某个聊天端口可转写，而是按顺序探测：本地平台 API 是否支持 `/audio/transcriptions`、配置的 `local-asr-api` 是否可用、Python 是否可 import `whisper`。如果返回 `setup_python_whisper_required`，说明没有可用本地 ASR API 且本机 Python 还不能 import `whisper`，在用户允许安装/下载后运行：

   ```bash
   python scripts/setup_whisper_backend.py \
     --install-package \
     --download-model \
     --model "$ASR_MODEL" \
     --json-out "$PROJECT_ROOT/whisper_setup_report.json"
   ```

   如果返回 `run_local_platform_asr_api` 或 `run_local_asr_api`，使用报告里的 `ASR_BASE_URL` 调用本地 `/audio/transcriptions`。如果用户明确选择外部 ASR 命令或 `mlx_whisper`，按对应路线执行；否则不要用临时 pip 命令、乱猜本地入口或把只支持 chat 的翻译/QC 服务当成 ASR。

   无台本时优先使用当前机器上“识别日语耳语最好”的 ASR。音源选择遵循：用户指定 > 可对齐的无 SE MP3 > 可对齐的无 SE WAV > 原音频。若无 SE 文件未能和普通音频对上，或 MP3 看起来像试听/裁剪/异常小文件，先核对再使用；最终字幕仍输出到 `$FINAL_SUBTITLE_DIR`，不是 ASR 输入目录或音频子目录。如果音频很难、耳语很多、BGM 大，可考虑：

   - 保留 `language=ja`
   - 关闭 `condition_on_previous_text`
   - 使用初始提示说明“成人向日语 ASMR，耳语、吐息、拟声多”
   - 对特别难的音频分段重跑或换更强模型

   ASR 优化必须谨慎使用。优先用户指定音源；未指定时才优先可对齐的无 SE 音源，并在同轨道无 SE MP3/WAV 中优先 MP3。若所选后端支持 VAD，可用它跳过长静音或纯环境声，但不能切掉低声耳语、喘息中的有效台词、重要停顿或安静对白。如果需要对长音频分段，使用 overlap/stride 防止边界截断，并在后端支持时把前一段 transcript 作为下一段 prompt/context，保持词汇、称呼和语气一致。分段 ASR 必须保留分段级 manifest 或等价记录，保证中断后只重跑受影响分段；现有整文件 ASR 仍保留音频文件级断点续跑。对于喘息、耳舐、亲吻等重复音效，后续字幕可以简化成短提示或少量节奏，不要让 ASR/翻译堆出无意义重复文本墙。

   长音频或多次试跑前，可以先准备保守的 ASR 音频缓存和分段恢复计划。这个步骤不会擅自丢弃低声内容；默认只写 segments manifest，只有显式 `--normalize` 时才用 ffmpeg 生成 16k mono WAV：

   ```bash
   python scripts/prepare_asr_audio_cache.py "$ASR_INPUT_DIR" \
     --cache-dir "$PROJECT_ROOT/asr_prepared" \
     --recursive \
     --segment-sec 900 \
     --overlap-sec 8 \
     --json-out "$PROJECT_ROOT/asr_prepared/asr_prepared_report.json"
   ```

   双人/多人左右耳语补漏只按需执行。主 ASR 后可以先跑轻量候选扫描，只生成报告，不自动合并字幕：

   ```bash
   python scripts/detect_channel_activity.py \
     "$AUDIO_FILE" \
     --main-asr "$ASR_DIR/$TRACK_STEM.ja.asr.srt" \
     --json-out "$PROJECT_ROOT/channel_recovery/$TRACK_STEM/channel_activity_candidates.json"
   ```

   检测不只看主 ASR 空白，也会把弱覆盖当候选信号，例如主 ASR 只有 `……`、`...`、极短喘息/拟声/触发音，或长时间音频只对应极短文本。如果报告中出现 `needs_user_disambiguation` 候选，必须明确提醒用户甄别：这段可能是有效台词，也可能只是 ASMR 音效、BGM、喘息或摩擦声。若用户指出某段漏字幕，或 QC/抽听发现主 ASR 长空白/弱覆盖但音频里有有效台词，读取 `docs/channel_recovery.md`，只对候选时间窗切左右声道 clip：

   ```bash
   python scripts/prepare_channel_recovery.py \
     "$AUDIO_FILE" \
     --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM" \
     --window 03:12-03:28
   ```

   也可从主 ASR 的长空白段生成候选：

   ```bash
   python scripts/prepare_channel_recovery.py \
     "$AUDIO_FILE" \
     --out-dir "$PROJECT_ROOT/channel_recovery/$TRACK_STEM" \
     --from-srt "$ASR_DIR/$TRACK_STEM.ja.asr.srt" \
     --min-gap 2.0 \
     --pad 0.25
   ```

   然后对 `$PROJECT_ROOT/channel_recovery/$TRACK_STEM/clips` 使用当前解析到的 ASR backend/model 转写。补漏结果只作为候选；不得自动覆盖主 `.ja.asr.srt` 或最终字幕。若确认需要并入主时间轴，先记录 review 决定，再重跑结构校验、翻译和 QC。

5. 修轻微 ASR 时间重叠

   Whisper ASR 有时会产生很小的时间重叠。先跑结构校验；如果只是轻微 overlap，可在翻译前做保守修复：

   ```bash
   python scripts/repair_asr_timestamps.py "$ASR_DIR" \
     --mode fix \
     --backup-dir "$PROJECT_ROOT/asr_timestamp_backups" \
     --json-out "$PROJECT_ROOT/asr_timestamp_repair_report.json"
   ```

   这个工具只允许自动修很小的 overlap，做法是把前一条字幕结束时间裁到后一条开始时间；它不会改编号、顺序或文本内容。中等和严重 overlap 只报告，不自动修。若已经存在对应 `.zh.srt`，默认会阻止只修 JA，避免破坏 JA/ZH 时间轴一致性。修完后必须再次跑结构校验。

   无论使用哪种 ASR，输出合约固定为 `$ASR_DIR/<track>.ja.asr.srt`，可选保留 `$ASR_DIR/<track>.ja.asr.json`。本地 API ASR 命令：

   ```bash
   export ASR_AUDIO_DIR="/path/to/asr_audio_dir"
   export ASR_DIR="$PROJECT_ROOT/asr_current"
   export ASR_PROMPT="これは日本語の成人向けASMR音声です。囁き、吐息、間、耳舐め、キス音、擬音が多いです。"

   python scripts/transcribe_openai_audio.py \
     "$ASR_AUDIO_DIR" \
     --out-dir "$ASR_DIR" \
     --base-url "$ASR_BASE_URL" \
     --model "$ASR_MODEL" \
     --glob "*.wav" \
     --language ja \
     --prompt "$ASR_PROMPT" \
     --project-root "$PROJECT_ROOT"
   ```

   Python Whisper fallback 命令：

   ```bash
   python scripts/transcribe_whisper.py \
     "$ASR_AUDIO_DIR" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --glob "*.wav" \
     --language ja \
     --project-root "$PROJECT_ROOT" \
     --initial-prompt "$ASR_PROMPT"
   ```

   如果用户明确选择 `mlx_whisper` 且当前环境已可 import，才使用 `batch_transcribe_mlx.py`。如果用户选择外部 ASR 命令或服务，按用户提供的调用方式执行，但最终仍必须产出同名 `.ja.asr.srt` 到 `$ASR_DIR`。

   ASR 脚本默认按音频文件断点续跑：已有可解析的 `<track>.ja.asr.srt` 会跳过；只有 `.ja.asr.json` 时会优先重建 SRT；每个跳过、成功或失败都会写入 `$ASR_DIR/asr_manifest.json`。只有用户明确要求重跑已完成 ASR 时才加 `--force`。

5. ASR 自检

   无台本时，翻译前先检查日文 ASR：

   - 是否出现明显幻觉：`ご視聴ありがとうございました`、`チャンネル登録`、非剧情广告语。
   - 是否大量漏掉耳语或把拟声识别成普通词。
   - 是否把连续音效识别成长串无意义文本。
   - 标题里的关键词是否在 ASR 中被识别正确。

   记录到 `review_notes.md`：

   - 低置信轨道。
   - 明显要人工注意的时间点。
   - 推测术语和角色关系。

6. 初翻

   默认使用 `auto` 后端选择：Windows/WSL 优先 Ollama；没有 Ollama 时回退到其他可用 OpenAI-compatible 服务；macOS 可继续优先使用 oMLX 的 OpenAI-compatible 本地 API。本机默认推荐翻译/QC 使用 `Qwen2.5-32B-Instruct-GGUF-Q4_K_M`。无台本时建议更小 chunk，例如 6 到 9 条，降低上下文丢失和 JSON 出错风险。

   先启动当前选择的本地推理服务，再设置当前翻译后端：

   ```bash
   # macOS/oMLX 示例：
   # omlx serve --port 8000
   #
   # Windows/WSL/Ollama 示例：
   # ollama serve
   ```

   ```bash
   export TRANSLATE_BASE_URL="${TRANSLATE_BASE_URL:-$LOCAL_MODEL_BASE_URL}"
   export TRANSLATE_MODEL="${TRANSLATE_MODEL:-Qwen2.5-32B-Instruct-GGUF-Q4_K_M}"
   export TRANSLATE_API_KEY="local-placeholder"
   export ZH_SRT_DIR="$PROJECT_ROOT/srt_work"
   export PROMO_ZH_SRT_DIR="$PROJECT_ROOT/promo_srt_work"
   export ZH_DIR="$FINAL_SUBTITLE_DIR"
   ```

   进入翻译前确认阶段切换：ASR 阶段已结束、`.ja.asr.srt` 已写入，当前服务已切换到翻译 chat 模型，`TRANSLATE_MODEL` 指向 chat 模型而不是 Whisper。若本地平台不能同时常驻 ASR 与翻译模型，先释放/卸载/切换 ASR 模型。随后用阶段检查确认当前模型真的能调用：

   ```bash
   python scripts/prepare_model_stage.py "$PROJECT_ROOT" translate \
     --previous-stage asr \
     --from-config \
     --api-key "$TRANSLATE_API_KEY" \
     --json-out "$PROJECT_ROOT/model_stage_translate.json"
   ```

   如果这里失败，先处理本地模型服务，不要直接进入翻译。

   随后解析当前模型适合的 chunk 默认值。agent 后续命令应读取 `chunk_profile_translate.json` 的 `defaults.translate`，不要继续固定套用同一组 chunk 参数：

   ```bash
   python scripts/resolve_chunk_profile.py "$PROJECT_ROOT" translate \
     --model-stage-report "$PROJECT_ROOT/model_stage_translate.json" \
     --json-out "$PROJECT_ROOT/chunk_profile_translate.json"
   ```

   ```bash
   python scripts/batch_translate_srt_omlx.py \
     --input-dir "$ASR_DIR" \
     --output-dir "$ZH_SRT_DIR" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9 \
     --chunk-mode dynamic \
     --min-chunk-size 4 \
     --max-chunk-size 18 \
     --target-chars 700 \
     --hard-chars 1100 \
     --context-before 3 \
     --context-after 3 \
     --project-root "$PROJECT_ROOT"
   ```

   进度条默认启用，不需要额外参数。批量入口会显示两层进度：

   - `batch translate`：总文件进度，单位是 file，会显示当前正在处理或跳过的文件名。
   - 当前文件进度：单位是 chunk，会显示当前字幕编号范围、已完成字幕数、耗时和预计剩余时间。

   `batch_translate_srt_omlx.py` 会自动调用 `translate_srt_omlx.py --progress-position 1`，把当前文件进度放到第二行。平时使用上面的批量命令即可。若只想单独翻译或调试一个文件，可以直接调用单文件脚本：

   ```bash
   python scripts/translate_srt_omlx.py \
     "$ASR_DIR/<file>.ja.asr.srt" \
     "$ZH_SRT_DIR/<file>.zh.srt" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9 \
     --chunk-mode dynamic \
     --min-chunk-size 4 \
     --max-chunk-size 18 \
     --target-chars 700 \
     --hard-chars 1100 \
     --context-before 3 \
     --context-after 3 \
     --project-root "$PROJECT_ROOT"
   ```

   翻译 chunk 以语义连续性优先，字符预算只作为上限。脚本会为每个 chunk 携带前后 halo 作为上下文，但只要求模型输出目标编号。翻译结果旁会生成 `<file>.zh.srt.flags.json`，记录 `asr_uncertain`、`adult_term`、`speaker_ambiguous`、`pronoun_ambiguous`、`onomatopoeia`、`long_line`、`possible_noise`、`needs_context` 等候选风险标签，供后续 QC 聚焦使用。

7. 结构校验

   每次翻译和手修后都必须确认：

   - 中文 SRT 与日文 ASR 条目数一致。
   - 编号、开始时间、结束时间一致。
   - 无空字幕。
   - 无时间重叠。

   推荐使用正式校验脚本：

   ```bash
   python scripts/validate_subtitles.py \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --json-out "$PROJECT_ROOT/validate_report.json"
   ```

   结构校验通过后，做一次 ASMR 可读性检查。该检查只输出 warning，不自动拆字幕、不改时间轴：

   ```bash
   python scripts/subtitle_readability.py \
     "$ZH_SRT_DIR" \
     --max-cps 10 \
     --json-out "$PROJECT_ROOT/readability_report.json"
   ```

8. 无台本内容校对

   先扫高风险词：

   ```bash
   python scripts/scan_subtitle_risks.py \
     "$PROJECT_ROOT" \
     --json-out "$PROJECT_ROOT/risk_report.json"
   ```

   默认风险规则文件是 `data/subtitle_risk_patterns.json`。如需测试临时规则，可用 `--rules <rules.json>` 指定。

   如果脚本暂时不可用，可临时用 `rg` 扫语料库中的高风险词，但正式流程优先使用 `scan_subtitle_risks.py`，便于保留报告。

   再人工通读。无台本时要特别注意：

   - 前后剧情是否连贯。
   - 人称是否稳定。
   - 同一术语是否前后统一。
   - 音效段是否被误译成台词。
   - ASR 是否把 `シコ/しっこ`、`精液`、`童貞喪失` 等识别错。
   - 长时间连续重复的拟声是否被压缩到可读长度。短段拟声可保留少量节奏，例如 `啾……啾啾……`、`嗯、嗯……哈啊……`；持续数秒或跨多条字幕的同类音效，优先写成 `[持续亲吻声]`、`[长段舔耳声]`、`[持续摩擦声]`、`[长长的喘息声]`。
   - 校对拟声词时必须对照日文 ASR；如果有外部说明或后续取得台本，也要一并对照。先判断原文拟声对应的是亲吻、舔耳、手冲摩擦、抽插、喘息还是其他音效，再决定中文提示；不要只看中文重复字符自行猜音效类型。
   - 拟声中夹着有效台词时，只压缩纯音效部分，保留实际台词；不要因为压缩音效而删掉剧情信息。

9. 必须模型质检

   把日文 ASR 和中文字幕成对喂给当前配置的本地/项目 QC 模型，让它只输出“明显问题”，不要让它大面积改风格。无台本项目必须至少跑一轮完整模型质检；若后续批量接受建议或大幅手修，还要再跑一次高风险词扫描和结构校验。这里的“模型质检”必须是通过 `scripts/qc_srt_omlx.py` 调用 `QC_BASE_URL`/`QC_MODEL` 或等价的明确配置接口，不是 agent 用自身模型读一遍字幕。

   进入 QC 前先解析 QC 工况模型，后续命令使用解析结果；如果本地 QC 服务不可用，停下报告或让用户改 backend/model，不要用 agent 自己的模型顶替：

   ```bash
   python scripts/manage_model_profile.py resolve "$PROJECT_ROOT" qc --from-config
   ```

   随后必须做 QC 阶段模型就绪检查，尤其是翻译模型和 QC 模型不同时：

   ```bash
   python scripts/prepare_model_stage.py "$PROJECT_ROOT" qc \
     --previous-stage translate \
     --from-config \
     --api-key "$TRANSLATE_API_KEY" \
     --json-out "$PROJECT_ROOT/model_stage_qc.json"
   ```

   若返回 `FAIL`，不要运行 QC。HTTP 500 常见原因是上一阶段翻译模型仍占用显存/内存、QC 模型加载失败或过大、本地后端不支持按请求里的 `model` 自动热切换、模型名不匹配，或服务需要手动重载/重启。先让用户释放/卸载上一模型或在本地后端切到 QC 模型，再重跑阶段检查。

   随后解析 QC chunk 默认值。agent 后续命令应读取 `chunk_profile_qc.json` 的 `defaults.qc`，根据模型类别选择 light/deep chunk 大小、`context_halo`、`qc_tier` 和必要的 `reasoning_token_budget`：

   ```bash
   python scripts/resolve_chunk_profile.py "$PROJECT_ROOT" qc \
     --model-stage-report "$PROJECT_ROOT/model_stage_qc.json" \
     --json-out "$PROJECT_ROOT/chunk_profile_qc.json"
   ```

   推荐使用脚本：

   ```bash
   python scripts/qc_srt_omlx.py \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --out "$PROJECT_ROOT/qc_report.json" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$QC_BASE_URL" \
     --model "$QC_MODEL" \
     --chunk-size 18 \
     --chunk-mode dynamic \
     --qc-tier two-pass \
     --context-halo 3 \
     --flags-dir "$ZH_SRT_DIR" \
     --context "作品主题、角色关系、标题关键词、已知 ASR 易错词" \
     --project-root "$PROJECT_ROOT"
   ```

   QC 默认会在 `$PROJECT_ROOT/qc_report_chunks/` 保存每个 chunk 的结果和 manifest，中断后再次运行会跳过签名一致的成功 chunk。`--qc-tier two-pass` 会先跑全量轻 QC，再根据翻译 flags、风险词、长句、残留日文/乱码等信号对高风险片段跑小 chunk 深 QC。动态 chunk 会自动缩小高风险、长句或密集 ASMR 内容附近的范围；chunk 签名以当前 chunk、halo、模型、base URL、prompt 版本、参数和上下文为准，不再因为整份文件一处修改而全量失效。需要完全固定切分时再使用 `--chunk-mode fixed`。

   推荐质检提示：

   ```text
   你是日译中 ASMR 字幕质检员。检查同编号日文 ASR 与中文字幕。
   只标出明显问题：错译、ASR 误识别导致中文荒唐、残留日文/英文混杂、不符合上下文、中文很不自然。
   不要挑风格小毛病；如果可接受就不要输出。
   输出 JSON 数组，每项 {"i":编号,"problem":"简短说明","suggest":"建议改成的中文字幕"}。
   ```

   注意：

   - 第一轮模型 QC 后，agent 必须处理 `qc_report.json` 中所有明确问题，并完成一轮修正；这一步不是可选项。
   - 第一轮、第二轮以及后续任何模型 QC/精修 QC，都必须调用当前解析到的 QC backend/base URL/model。agent 自身模型只能负责编排、读报告、对照证据和标记 accept/reject/defer，不能充当 QC 模型。
   - agent 处理 QC 建议时，不能仅凭自身模型判断；必须对照日文 ASR、当前中文字幕、相邻字幕、作品标题/设定和语料库规则。agent 的职责是执行证据驱动的修正流程，而不是凭感觉重翻。
   - 模型质检建议只能作为候选，不可照单全收。
   - 长文件要小分块，避免模型卡住或上下文漂移。
   - 确定修改前要回看相邻字幕和音轨标题；明确正确的建议应修正，明显违背上下文的建议记录为误报，无法判断的条目标为待复核。
   - 第一轮 QC 修正后必须再跑结构校验、高风险扫描和可读性检查。
   - 如果需要第二轮 QC、仍有待复核条目、模型建议互相冲突，或用户想介入，再生成人工审阅材料。
   - 对“ASR 高频同音错词”要按整部作品统一扫一遍，不能只改单个命中。例如 `射精` 可能被识别成 `写真/书生`，`オナニー` 可能被识别成 `オーナー`。

   需要人工介入时，可生成 QC 审阅模板：

   ```bash
   python scripts/review_qc_report.py \
     "$PROJECT_ROOT/qc_report.json" \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --out "$PROJECT_ROOT/qc_review.md" \
     --json-out "$PROJECT_ROOT/qc_review_items.json"
   ```

   人可以直接基于 `qc_report.json` 提意见，也可以在 `qc_review.md` 中逐条标记 `accept`、`reject` 或 `defer`。`review_qc_report.py` 只生成审阅材料，不自动改字幕。

   如果第一轮强制 QC 和修正后，用户仍觉得台词不满意，把后续处理作为“追加 QC 精修功能”，而不是重做基础流程。每一轮都要有独立目录，避免覆盖第一次 `qc_report.json`：

   ```bash
   python scripts/manage_qc_refinement.py start \
     "$PROJECT_ROOT" \
     --mode auto \
     --focus "用户指出的问题类型，例如语气太硬、亲密感不足、某角色称呼不稳"
   ```

   如果用户提供了引导词、风格说明或指出具体翻译问题，使用 guided 模式：

   ```bash
   python scripts/manage_qc_refinement.py start \
     "$PROJECT_ROOT" \
     --mode guided \
     --focus "台词精修" \
     --user-guidance "现在太硬了，希望更亲密、更像 ASMR 口语，但不要过度改写"
   ```

   该命令会创建 `$PROJECT_ROOT/qc_refinement/round_NN/manifest.json`、`context_profile.md` 和 `next_steps.md`。`context_profile.md` 会记录自动识别到的作品情境、轨道抽样和用户引导。按 `next_steps.md` 执行：通过配置的本地/项目 QC 模型重新跑一轮聚焦 QC、生成 review items、由 agent 基于证据标记 `accept/reject/defer`、应用 accepted 项、再跑结构/风险/可读性检查。用户仍不满意时再开下一轮。任何追加轮次都不能跳过本地 QC 调用而改成 agent 自身模型 QC。

   若 agent 已经按证据确认一批明确问题，可直接编辑 `qc_review_items.json`：把明确应修的条目标为 `"decision": "accept"`，必要时把最终译文写入 `"replacement"`；误报标为 `reject`，无法判断标为 `defer`。随后先 dry-run，再正式应用：

   ```bash
   python scripts/apply_qc_decisions.py \
     "$PROJECT_ROOT/qc_review_items.json" \
     --zh-dir "$ZH_SRT_DIR" \
     --json-out "$PROJECT_ROOT/qc_apply_report.json"
   ```

   ```bash
   python scripts/apply_qc_decisions.py \
     "$PROJECT_ROOT/qc_review_items.json" \
     --zh-dir "$ZH_SRT_DIR" \
     --apply \
     --backup-dir "$PROJECT_ROOT/qc_apply_backup" \
     --json-out "$PROJECT_ROOT/qc_apply_report.json"
   ```

   只允许应用已确认的 `accept` 项；应用后必须再跑结构校验、高风险扫描和可读性检查。

10. 听感抽检

   无台本项目建议至少抽检：

   - 每条音频开头 1 到 2 分钟。
   - 每条音频高潮/高密度拟声段。
   - 每条音频结尾。
   - 所有被高风险扫描命中的位置。

   如果用户允许，可打开音频播放器或用本机工具抽听。无法抽听时，在交付时说明“未进行听感抽检”。

11. 附加音频处理

   - 促销/试听、EX/free talk、bonus、DLC、特典等音频默认都要单独 ASR、单独翻译、单独校对。
   - 不要简单复制本篇字幕，因为附加音频可能剪辑、重录、删改句子，DLC/特典也可能有独立剧情。
   - 促销/试听更容易有截断句，要让中文可读，但不要补不存在的剧情。
   - 只有用户明确要求只翻正片、跳过促销/试听、跳过 DLC/特典或指定文件范围时，才排除对应音频；排除理由要写入项目记录或最终说明。

12. 导出最终字幕

   结构校验、可读性检查、人工修订、模型质检和必要抽听都通过后，按用户选择导出最终字幕。默认把 SRT 中间稿导出为 WebVTT `.zh.vtt`；如果用户要求 `srt`，导出 `.zh.srt`；如果用户要求 `both`，同时导出 `.zh.srt` 和 `.zh.vtt`。

   ```bash
   export OUTPUT_FORMAT="vtt"  # 可改为 srt 或 both

   python scripts/export_final_subtitles.py \
     "$ZH_SRT_DIR" \
     "$ZH_DIR" \
     --format "$OUTPUT_FORMAT" \
     --glob "*.zh.srt" \
     --overwrite \
     --json-out "$PROJECT_ROOT/export_report.json"
   ```

   若有促销/试听、EX/free talk、bonus、DLC、特典等附加音频，使用对应的附加音频 SRT 工作目录再导出到同一个 `$FINAL_SUBTITLE_DIR`：

   ```bash
   python scripts/export_final_subtitles.py \
     "$PROMO_ZH_SRT_DIR" \
     "$FINAL_SUBTITLE_DIR" \
     --format "$OUTPUT_FORMAT" \
     --glob "*.zh.srt" \
     --overwrite \
     --json-out "$PROJECT_ROOT/promo_export_report.json"
   ```

   导出后确认该目录只包含最终 `.zh.vtt/.zh.srt` 字幕，不混入 ASR、SRT 工作稿、QC 报告或 review notes：

   ```bash
   python scripts/validate_subtitles.py \
     --final-dir "$FINAL_SUBTITLE_DIR" \
     --json-out "$PROJECT_ROOT/final_validate_report.json"
   ```

   如需回修，先改 SRT 中间稿并重新校验，再重新导出最终字幕。

13. 更新学习库

   每完成一个作品，都要从本次翻译、模型 QC、风险扫描、可读性检查、抽听/台本复核和人工修正中提炼可复用经验。学习库维护规则见 `docs/learning_library_guide.md`；交付前必须做 learning self-check，确认没有把未证实内容写成全局规则。

   学习分三层：Skill 内置 `references/` 和 `data/subtitle_risk_patterns.json` 只读；用户长期学习库存放跨作品确认经验；`$PROJECT_ROOT/learning/` 只保存本次作品的 work record 和 shared corpus review 草稿。普通翻译任务不要直接写 Skill 包内 `references/`。

   更新流程：

   - 每个完成的作品都必须在 `$PROJECT_ROOT/learning/work_record.md` 追加工作记录。
   - work-only 内容只留在 work record，不晋升到用户长期库。
   - 收尾时询问用户是否还有要修正的地方，以及是否现在整理学习库；若还有修正需求，先完成修正和受影响检查。
   - 可复用风格、术语、风险说明先进入 shared corpus review packet 或长期 review 队列；只有用户明确 approve 的条目才能晋升到用户长期学习库。
   - pending 内容写入 work record 或用户长期 `references/pending.md`，不要写成定论。
   - false-positive 写入用户长期 `references/risk-notes.md`，说明误报边界。
   - 可机械扫描的确认规则写入用户长期 `data/subtitle_risk_patterns.local.json`。

   先解析学习路径，再生成 work record 草稿：

   ```bash
   python scripts/resolve_learning_paths.py \
     "$PROJECT_ROOT" \
     --json-out "$PROJECT_ROOT/learning_paths.json"

   python scripts/update_learning_library.py \
     "$PROJECT_ROOT" \
     --learning-paths "$PROJECT_ROOT/learning_paths.json" \
     --append-work-record \
     --out "$PROJECT_ROOT/learning/learning_update.md"
   ```

   如果发现音声根目录或音频目录里散落 `reference/`、`references/`、`learning/` 等文件夹，先收集到 work record 的 imported 目录，不要继续在那里写：

   ```bash
   python scripts/collect_learning_artifacts.py \
     "$SOURCE_PROJECT_DIR" \
     --work-record-dir "$PROJECT_ROOT/learning" \
     --copy \
     --json-out "$PROJECT_ROOT/learning/imported_learning_artifacts.json"
   ```

   收尾时询问用户是否还有要修正的地方，或是否现在整理学习库。若用户选择整理学习库，再询问 shared corpus review 选择：`agent-assisted`、`user-review` 或 `skip`。除非用户明确 approve 具体条目，不要把项目候选直接写入用户长期库。若用户选择进入 review，用：

   ```bash
   python scripts/manage_shared_corpus_review.py \
     "$PROJECT_ROOT" \
     --choice agent-assisted \
     --evidence "$PROJECT_ROOT/learning/work_record.md" \
     --evidence "$PROJECT_ROOT/qc_report.json" \
     --json-out "$PROJECT_ROOT/learning/shared_corpus_review_report.json"
   ```

   当前项目 review 选择处理完后，检查长期 review 缓冲区；如果还有 pending 项，询问用户是否现在处理：

   ```bash
   python scripts/manage_shared_corpus_review.py \
     --list-queue \
     --json-out "$PROJECT_ROOT/learning/review_queue_status.json"
   ```

## 无台本质量标准

必须做到：

- 可挂载：结构校验 OK。
- 可读：中文没有明显机器腔和荒唐词。
- 合情境：人物关系、称呼、语气基本稳定。
- 已质检：完成模型 QC，并处理或记录所有明确问题。
- 不乱编：不确定内容不擅自扩写。
- 可追踪：把疑点写入 `review_notes.md` 或最终说明。

交付时说明：

- 已完成哪些目录。
- 最终字幕格式：默认 WebVTT `.vtt`，或用户指定的 `.srt` / `both`。
- 是否发现并完成了附加音频，例如促销/试听、EX/free talk、bonus、DLC、特典；如有明确跳过，说明用户指定的范围或跳过理由。
- 模型质检是否完成，`qc_report.json` 路径在哪里。
- `project_config.json` 路径和最终 `output_format`。
- 是否做了听感抽检。
- 有哪些未能完全确认的句子或轨道。
- 本次新增了哪些项目级经验，或说明没有发现值得沉淀的新规则。
- 学习自检摘要：哪些内容进入 work record，哪些进入 shared corpus review packet/queue，哪些保持 pending/project-only，哪些候选被判定为误报或不学习。
- 说明 shared corpus review 状态：用户选择 `agent-assisted`、`user-review`、`skip`，或尚未选择；未获明确 approve 的内容不得称为已进入 shared corpus。
- 说明 review 缓冲区是否还有 pending packet；如有，询问用户是否现在处理或继续保留。
