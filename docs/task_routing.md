# ASMR 字幕任务分流规则

用途：开工前先判断当前请求属于哪条路线，再读取对应 workflow 和参考资料。agent 负责分流；脚本只做检查、报告、转换和可重复步骤。

## 分流原则

- 先盘点输入：所有音频、官方台本/初稿/PDF/TXT/HTML、已有 `.ja.asr.srt`、已有 `.zh.srt`/`.zh.vtt`、促销/试听/DLC/EX/bonus 目录、用户要求的输出格式。
- 开工第一步必须用 `scripts/resolve_project_context.py` 从源路径和父目录解析 `WORK_ID`、`PROJECT_ROOT`、`SOURCE_PROJECT_DIR` 与 `FINAL_SUBTITLE_DIR`。源文件夹名是 `RJxxxx` 时必须识别为作品号。
- `SOURCE_PROJECT_DIR` 默认就是源 ASMR 作品目录，即识别到的 RJ 父目录或音频源上级作品目录；不再默认创建 `generated_subtitles/<WORK_ID>`。除非用户明确指定 `--output-root` 或 `--project-root`，不要把项目输出另放到工作区。
- `PROJECT_ROOT` 默认是 `$SOURCE_PROJECT_DIR/subtitle_project/`，用于工程文件和中间文件；最终 `.zh.vtt/.zh.srt` 放在 `$FINAL_SUBTITLE_DIR`，默认是 `$SOURCE_PROJECT_DIR/subtitles/`。
- 若音频包里同时存在有 SE/无 SE 版本，用户指定音源优先；未指定时，用 `scripts/select_asr_audio_source.py` 按轨道匹配。只有能和普通音频对齐且 `requires_review=false` 的无 SE 文件才作为默认 ASR 输入；同轨道无 SE 同时有 MP3/WAV 时默认选 MP3，除非报告提示疑似试听、裁剪、占位或映射不清。
- 翻译范围必须在 Preflight 阶段确认。先用 `scripts/scan_audio_scope.py` 列出源作品文件夹下发现的音频文件夹，再询问用户本轮要翻译哪些文件夹或具体文件。试听、DLC、EX/free talk、bonus、特典等不能被默认歧视或跳过；只有用户确认 `all` 时才全量处理，用户选择部分文件夹/文件时，把这个 scope 写入 `run_profile.json`。
- 已确认本轮范围且确实需要新 ASR 后，运行 `scripts/resolve_wav_only_asr_tracks.py`。只要选中 ASR 输入里存在 WAV-only 轨道，就列出这些轨道并询问用户：仅对它们生成临时 16 kHz 双声道 MP3 缓存提速，还是直接跑原始 WAV。已有可靠 MP3 的本篇轨道保持直用，不能重新转换；已有可复用 `.ja.asr.srt` 时不问此题。将选择、报告和受影响轨道写入 `run_profile.json`。
- 默认最终输出为 `.zh.vtt`；用户可明确选择 `srt` 或 `both`。`.zh.srt` 默认仍是工作中间稿。
- 不因为当前机器不能新跑 ASR 就阻塞已有 ASR 项目的翻译、QC、风险扫描、可读性检查和导出。
- 翻译和 QC chunk 以语义连续性优先，字符/token 预算只作为上限。优先使用动态 chunk 和 halo 上下文；halo 只用于理解，不要求模型输出上下文编号。
- 质量底线不可被任何 chunk、缓存、速度或自动化优化破坏：保持 SRT 编号、顺序、开始时间、结束时间不变；翻译必须覆盖所有目标编号；context halo 不能进入输出；QC 建议只能作为候选；ASMR 语义、角色关系、动作连续性优先于机械压缩；缓存只可复用到内容、模型、prompt/schema、参数和上下文签名一致的 chunk。
- Whisper 常见的小时间重叠属于 ASR 时间轴修复问题，不属于普通翻译/QC 阶段。只有 `scripts/repair_asr_timestamps.py` 这类专门的 ASR 修复工具可以在 ASR 后、翻译前处理轻微 overlap；大 overlap 只报告，不自动修。若已存在对应 `.zh.srt`，默认不要单独改 `.ja.asr.srt`。
- 翻译阶段生成的 `<file>.zh.srt.flags.json` 可用于后续 QC 分流。速度敏感时，QC 优先用 `--qc-tier two-pass`：全量轻 QC + 高风险深 QC。
- 新跑 ASR 前必须先用 `scripts/resolve_asr_route.py` 做只读分流；`asr_backend=auto` 默认先探测本地平台 API 端口是否支持 `/audio/transcriptions`，再探测配置的 `local-asr-api`，再使用 skill 自带 Python Whisper 脚本。若当前解释器和共享用户 ASR venv 都没有 `whisper`，最后才使用 `scripts/setup_whisper_backend.py` 这条受控 setup 路线安装 `openai-whisper` 并下载/缓存模型；默认安装目标是 `${ASMR_SUBTITLE_ASR_DIR:-~/ASMR-Subtitle-Translator/asr}/openai-whisper-venv`。不允许 agent 临时拼 pip 命令、下载未知模型或把 Whisper 反复装进自己的 active interpreter。
- ASR 脚本默认按音频文件断点续跑：可解析的 `.ja.asr.srt` 会跳过，只有 `.ja.asr.json` 时优先重建 SRT，并维护 `asr_manifest.json`。
- ASR 优化必须谨慎：用户指定音源优先；未指定时才优先可对齐的无 SE 音源，并在同轨道无 SE MP3/WAV 中优先 MP3。后端支持时可用 VAD 跳过长静音/纯环境声、用 overlap/stride 防止分段边界截断、把前一段 transcript 作为下一段 prompt/context、并保留分段级断点。不得因为 VAD 或切段漏掉低声耳语、喘息中的有效台词、重要停顿或安静对白；ASMR 重复喘息/耳舐/亲吻声后续可简化，不要让 ASR/翻译堆出无意义重复文本墙。
- 双声道/多人耳语补漏只按需触发：主 ASR 后可用 `scripts/detect_channel_activity.py` 做轻量候选扫描；用户指出漏字幕、QC/抽听发现疑似漏识别、或检测到主 ASR 长空白/弱覆盖但音频有声时，读取 `docs/channel_recovery.md`，用 `scripts/prepare_channel_recovery.py` 只对候选片段切左右声道。弱覆盖包括省略号、极短喘息/拟声/触发音、或长时间音频只对应极短文本。检测不确定时必须提醒用户甄别；补漏结果是候选，不自动覆盖主 ASR 或最终字幕。
- QC 脚本默认按 chunk 断点续跑，使用动态 chunk 和 `two-pass`：先全量 light QC，再对风险窗口 deep QC。长句、高风险词密集、ASMR 成人内容密集时自动缩小 chunk；简单短对白可适当放大。只有调试或精确复现旧结果时才固定 chunk 或改回 `standard`。
- 每条路线都必须在交付前完成结构校验、风险扫描、ASMR 可读性检查、第一轮强制模型 QC 和学习库更新，除非用户明确只要求一个只读检查、格式转换，或在 Preflight 中选择 `draft` 粗烤模式。学习库更新时要先解析学习路径，再把项目记录写入 `$PROJECT_ROOT/learning/work_record.md`；收尾时若用户选择整理学习库，可复用候选先进入 shared corpus review，只有明确 approve 的条目才迁移到用户长期学习库。

## 路线表

| 输入状态 | 路线 | 首要动作 | 必读文件 | 必做检查 |
| --- | --- | --- | --- | --- |
| 有音频和可用台本/文本 | 有台本完整流程 | 建立 `project_config.json`，跑或复用 JA ASR，再做台本对照 | `docs/asmr_subtitle_workflow_with_script.md`、`references/style.md`、`references/terms.md` | `validate_subtitles.py`、`scan_subtitle_risks.py`、`subtitle_readability.py`、强制 QC |
| 只有音频，无可用台本 | 无台本完整流程 | 建立配置，确认 ASR 后端；若已有 JA ASR 可跳过新 ASR | `docs/asmr_subtitle_workflow_no_script.md`、`references/style.md`、`references/terms.md`、`references/risk-notes.md` | 结构、风险、可读性、强制 QC；必要时听感抽检 |
| 已有 `.ja.asr.srt`，还没有中文字幕 | 复用 ASR 翻译路线 | 先校验 JA ASR 结构；环境检测不加 `--require-asr` | 按是否有台本选择 workflow | 与完整流程相同，但可跳过新 ASR |
| 已有 `.zh.srt` 工作稿 | QC/修正路线 | 成对校验 JA ASR 与 ZH SRT；跑风险、可读性和 QC | 对应 workflow、`references/risk-notes.md` | 修正明确 QC 问题后重跑结构、风险、可读性 |
| 已有最终 `.zh.vtt` 或 `.zh.srt` | 复查/再交付路线 | 找到对应工作稿；若没有工作稿，先决定是否从最终文件回建检查输入 | `references/style.md`、`references/risk-notes.md` | 至少风险和可读性；能成对时跑结构和 QC |
| 只要求 SRT/VTT 转换 | 格式转换路线 | 确认源字幕结构 OK，再用 `export_final_subtitles.py` 按 `output_format` 导出 | `docs/task_routing.md`、必要时 workflow 导出段 | `validate_subtitles.py --final-dir` 或源目录结构检查；确认成品目录无中间产物 |
| 只要求扫描/审阅 | 只读检查路线 | 不修改字幕；生成报告并总结问题 | `references/risk-notes.md`、`references/style.md` | 按请求跑结构、风险、可读性或 QC 审阅模板 |
| 促销/试听/DLC/EX/bonus 音频存在 | 附加音频并行子路线 | 为附加音频建立独立或清晰命名的 ASR/SRT 工作目录，最终字幕同样导出到 `$FINAL_SUBTITLE_DIR` | 对应 workflow 的促销/附加音频段 | 附加音频单独结构、风险、可读性、QC，不复用本篇结论 |
| 双人/多人左右耳语疑似漏识别 | 双声道补漏 ASR 子路线 | 保留主 ASR 时间轴，只对候选时间窗切 left/right clip 并单独 ASR | `docs/channel_recovery.md` | 补漏 review 后再决定是否修主 ASR；修后重跑结构、翻译/QC |

## 开工步骤

1. 运行 `scripts/resolve_project_context.py "/path/to/source_or_audio_root" --mkdir --json`，确定 `WORK_ID`、`PROJECT_ROOT`、`SOURCE_PROJECT_DIR`、`FINAL_SUBTITLE_DIR` 和 `SOURCE_AUDIO_DIR`。
2. 运行 `scripts/scan_audio_scope.py "$SOURCE_PROJECT_DIR" --json-out "$PROJECT_ROOT/audio_scope_report.json"`，递归识别源作品文件夹下的目标音频目录和文件，包括本篇、EX/free talk、bonus、DLC、特典、促销/试听；记录总数和分类。不要只看主线编号决定跳过文件。
3. 如果识别到 RJ 号且允许联网，先用 `scripts/fetch_dlsite_work_info.py` 抓取 DLsite 商品页元信息，保存到 `$PROJECT_ROOT/dlsite_work_info.json`。抓取失败不阻塞流程。
4. 新跑 ASR 前，用 `scripts/select_asr_audio_source.py` 扫音频版本；用户指定版本时用用户指定，否则按 `recommended_asr_files` 使用可对齐且 `requires_review=false` 的无 SE 文件，同轨道 MP3 优先于 WAV，warning 项先核对。
5. 新跑 ASR 时，在用户确认音频范围后运行 `scripts/resolve_wav_only_asr_tracks.py`；只有报告存在 WAV-only 轨道时才询问临时双声道 MP3 缓存或原始 WAV，并把选择写入 `run_profile.json`。随后读取 `docs/preflight_confirmation.md`，向用户确认质量模式、ASR/翻译/QC 模型和输出格式。
6. 读取 `docs/asmr_translation_corpus.md`，再按任务读取它指向的 reference。
7. 按路线读取有台本或无台本 workflow。
8. 创建或更新 `$PROJECT_ROOT/project_config.json` 和 `$PROJECT_ROOT/model_profile.json`，并用 `scripts/resolve_learning_paths.py "$PROJECT_ROOT"` 解析本轮学习路径。
9. 跑 `scripts/check_environment.py`；只有本轮必须新跑 ASR 时才加 `--require-asr`。
10. 任何 ASR/翻译/QC 模型调用前，先跑 `scripts/check_preflight.py "$PROJECT_ROOT" --stage <asr|translate|qc>`。
11. 如果本轮必须新跑 ASR，跑 `scripts/resolve_asr_route.py --config "$PROJECT_ROOT/project_config.json" --require-new-asr`。若返回 `blocked`，停下向用户确认 ASR 路线。
12. ASR 完成后，如果 `validate_subtitles.py` 报 `time_overlap`，可在翻译前跑 `scripts/repair_asr_timestamps.py` 做保守修复，并再次校验。
13. 进入对应 workflow 的执行步骤。

## 模型任务边界

- ASR/转文字任务：只负责从音频生成日文 `.ja.asr.srt`/JSON，不负责最终翻译判断。ASR 必须使用 Whisper 类模型和 `/audio/transcriptions`，或使用 Python Whisper 脚本。
- ASR 默认顺序：已有 `.ja.asr.srt` 先复用；新跑时优先探测 oMLX/LM Studio/Ollama 等本地平台 API 是否支持 `/audio/transcriptions`；然后使用配置的 `local-asr-api`；然后使用 Python Whisper；最后才走受控 setup。不要把只支持 chat 的翻译/QC 端口当成 ASR 入口。
- 翻译/QC 默认走 oMLX/Ollama/LM Studio 等本地 OpenAI-compatible chat 接口。本机默认推荐 `Qwen2.5-32B-Instruct-GGUF-Q4_K_M`；如果服务里的实际 model id 不同，以 `/models` 或用户配置为准。
- 用户或项目可以用 `$PROJECT_ROOT/model_profile.json` 为 ASR、翻译、QC 分别选择 backend/base URL/model。每个阶段开始前用 `scripts/manage_model_profile.py resolve "$PROJECT_ROOT" <asr|translate|qc> --from-config` 解析有效选择；不要把上一阶段模型自动带到下一阶段。
- 阶段切换时必须确认 `backend`、`base_url`、`model`、`interface`：ASR 用 Whisper + `/audio/transcriptions`，翻译/QC 用 chat 模型 + `/chat/completions`。如果本地平台不能同时常驻 ASR 与翻译模型，先释放/卸载/切换模型，再进入下一阶段。
- 本地模型调用纪律：凡是流程要求翻译、第一轮强制模型 QC、第二轮或后续追加 QC 精修，agent 必须调用解析到的本地/项目模型端口和脚本。agent 自身模型不等于翻译模型或 QC 模型，不能替代 `scripts/qc_srt_omlx.py` 的模型 QC。配置的本地 QC 服务不可用时，应停下报告或请求用户切换 backend/model，而不是悄悄自审。
- 如果已有 `.ja.asr.srt`，优先复用并校验；如果没有且所有 ASR 路线都不可用或用户不允许安装/下载，agent 必须停下询问。
- 翻译模型任务：负责把日文 ASR 或台本辅助下的日文字幕翻成 `.zh.srt`，必须保持编号和时间轴。
- QC 模型任务：只产出候选问题和建议，不直接改字幕；第一轮 QC 必跑。
- Agent 任务：分流、读 reference、调用脚本、证据驱动地修正字幕、复跑检查、按学习路径写 work record 并晋升 confirmed 经验、最后给出交付说明。

## 人工介入

人工审阅不强制。第一轮模型 QC 后，agent 必须处理所有明确问题并重跑检查；只有第二轮 QC、未决问题、冲突建议或用户主动要求时，才生成人工审阅材料或等待用户意见。
