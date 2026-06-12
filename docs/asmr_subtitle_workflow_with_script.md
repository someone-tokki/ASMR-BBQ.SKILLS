# 有对照台本的 ASMR 烤肉工作流

适用场景：作品文件夹内有官方台本、初稿台本、PDF、TXT、HTML、字幕文本或类似可对照文本，需要为每条音频生成单独可挂载的简体中文字幕。

本工作流基于 `RJ01201653` 的实践整理。执行前先用 `docs/task_routing.md` 确认属于有台本路线，再阅读 `docs/asmr_translation_corpus.md` 索引，并按需要加载 `references/style.md`、`references/terms.md` 和 `references/risk-notes.md`。完成后把新学到的术语、错词和风格规则追加回对应 reference 或结构化风险库。

## 目标

- 每条音频生成独立中文字幕；工作中间格式可继续使用 `.zh.srt`。最终交付默认导出 WebVTT，即 `.zh.vtt`；如果用户明确要求，也可交付 `.zh.srt` 或同时交付两种格式。
- 保持字幕时间轴、编号、条目数与日文 ASR 对齐。
- 中文自然、有人情味、符合人物关系和场景，不生硬直译。
- 拟声词、耳语、喘息、亲吻、舔耳、长段重复音效可简化，但不能误改剧情。
- 以台本作为剧情、措辞和专有设定的主要参考，用它校对 ASR 和翻译；但不要直接把台本硬切成字幕，除非用户明确要求。

## 输入与输出

输入：

- 原始 ASMR 目录，例如 `/Users/someone_tokki/Desktop/asmr/RJxxxx`
- 音频文件目录，通常包含本篇、EX、促销/试听部分
- 对照台本，例如 PDF/TXT/HTML
- 可用的 ASR/翻译工具和模型。工具可以变化，流程不绑定某个固定模型。

输出：

- 日文 ASR：`generated_subtitles/<work_id>/<asr_dir>/*.ja.asr.srt`
- 中文 SRT 中间稿：`generated_subtitles/<work_id>/srt_work/*.zh.srt`
- 中文本篇字幕：默认 `generated_subtitles/<work_id>/<原音频文件夹名>/*.zh.vtt`；用户指定 `srt` 或 `both` 时可输出 `.zh.srt` 或两者
- 促销 SRT 中间稿：`generated_subtitles/<work_id>/promo_srt_work/*.zh.srt`
- 促销字幕：默认 `generated_subtitles/<work_id>/<原促销音频文件夹名>/*.zh.vtt`；用户指定 `srt` 或 `both` 时可输出 `.zh.srt` 或两者
- 可选比对报告：`generated_subtitles/<work_id>/asr_vs_script_report.md`

字幕成品目录必须与原始音频目录同名。若原始作品内有 `WAV 本編/`、`プロモーション用音声/`、`音声/` 等音频文件夹，输出目录中也建立同名文件夹，只放该文件夹音源对应的最终字幕。默认最终字幕为 `.zh.vtt`；用户指定 `srt` 或 `both` 时，可放 `.zh.srt` 或两种格式。ASR、SRT 中间稿、QC 报告、review notes 等工作产物留在作品输出根目录或专用工作目录中，不与成品字幕混放。

DLsite 音声自带字幕常见格式是 WebVTT。默认最终导出格式按 `.vtt` 处理；如果用户明确要求 `srt` 或 `both`，按用户选择交付。`.zh.srt` 默认仍作为 ASR、翻译、校验和手修阶段的中间格式保留。

## 工具选择原则

工具和模型不是流程的一部分，只是实现手段。每次开工时先确认当前机器上可用的 ASR、翻译后端、模型路径和 API 地址，再选择“当下效果最好且速度可接受”的组合。跨平台规则见 [platform_compatibility.md](platform_compatibility.md)。

如果使用第三方平台或本地推理服务，比如 Ollama、oMLX、LM Studio 或类似工具，优先走它们官方提供的调用接口。若该平台提供的是 OpenAI-compatible API，就优先直接调用这套接口，而不是通过间接包装、非官方桥接或界面自动化去调用。Windows/WSL 默认优先 Ollama；没有 Ollama 时，agent 应按环境检测结果回退到其他可用 OpenAI-compatible 后端。端口优先采用平台官方默认端口；只有在默认端口被占用、服务不可用或平台明确要求时，才改用其他端口。这样更容易：

- 观察模型是否真的在运行。
- 查看实际占用的端口、请求和日志。
- 排查失败是出在模型、服务还是脚本。
- 保持脚本、监控和后续排障方式一致。
- 尽量减少“同一工具在不同端口间漂移”带来的混淆。

本次 `RJ01201653` 的可用组合仅作为示例：

- ASR 示例：`mlx-community/whisper-large-v3-mlx-4bit`
- ASR 模型路径示例：`~/.lmstudio/models/mlx-community/whisper-large-v3-mlx-4bit`
- 默认翻译后端：`auto`。Windows/WSL 优先 Ollama；macOS 可继续使用 oMLX 的 OpenAI-compatible 本地 API；LM Studio、本机其他推理服务或云端模型作为 fallback。
- 翻译模型示例：`Qwen3.6-27B-MLX-VL-oQ6`
- 依赖示例：`tqdm`, `mlx_whisper`, `pdftotext`

替换原则：

- ASR 可以换成更强 Whisper、WhisperX、其他日语 ASR 或云端 ASR，只要输出可解析的日文 SRT/JSON。
- 翻译模型默认走当前平台可用的高质量日译中模型；Windows/WSL 优先 Ollama，macOS 可优先 oMLX。如需更换成本地其他后端或云端模型，必须仍能稳定按编号返回中文字幕。
- 如果模型支持“关闭思考/隐藏 reasoning”，应关闭，避免污染字幕输出。Qwen 类模型可使用 `chat_template_kwargs: {"enable_thinking": false}`。
- 若从 oMLX 换到其他后端，优先保留 OpenAI-compatible API 形式，便于复用脚本；否则可替换脚本但保持同样的输入输出约定。
- 如果需要访问 Metal、LM Studio/oMLX/其他本地 API、桌面音频目录或下载模型，agent 应直接请求用户批准，不要绕过权限。
- 长任务应优先使用脚本侧进度条展示进度；无报错时不要每几个分块向用户汇报一次，只有出现错误、需要用户决策或阶段完成时再说明。
- 模型质检是必经步骤，不是可选项。有台本时仍以台本为主要依据，模型 QC 只作为辅助补漏，用来发现 ASR 同音错词、翻译模型误解上下文、局部台词逻辑不通等问题。

## 执行步骤

1. 盘点文件

   - 列出作品目录下音频、台本、促销/试听音频。
   - 确认哪些是本篇，哪些是 EX/Free Talk，哪些是促销。
   - 不移动、不改写原始音频和原始台本。
   - 如果目录名或用户输入中识别到 RJ 号，且允许联网，可抓取 DLsite 商品页元信息：

   ```bash
   python scripts/fetch_dlsite_work_info.py "RJxxxx" \
     --out "generated_subtitles/<work_id>/dlsite_work_info.json" \
     --allow-fail
   ```

   抓取失败不阻塞流程；成功时，标题、社团、标签和简介只作为低强度上下文，不能覆盖台本证据。

   如果音频包里可能同时有有 SE/无 SE 版本，先做 ASR 音源选择扫描：

   ```bash
   python scripts/select_asr_audio_source.py "/path/to/audio_root" \
     --json-out "generated_subtitles/<work_id>/audio_source_report.json"
   ```

   默认优先使用扫描报告推荐的无 SE 音频跑 ASR，因为背景声和效果音更少，日语耳语识别通常更准。但这只是默认偏好；如果用户明确指定使用有 SE、通常版或某个目录/文件，就按用户指定，并可用 `--user-selected "/path/to/user_choice"` 记录该覆盖选择。

2. 读取语料库

   - 先读 `docs/asmr_translation_corpus.md` 索引。
   - 翻译前读 `references/style.md` 和 `references/terms.md`。
   - QC 和扫雷前读 `references/risk-notes.md`。
   - 记录本作设定：人物称呼、敬语程度、角色关系、关键术语。
   - 本作若有专有词，先建立临时术语表，翻译结束后整理进对应 reference。

3. 建立项目配置记录

   开工后尽早创建或更新 `generated_subtitles/<work_id>/project_config.json`。配置只记录当前项目的目录、模型、输出格式和报告路径，不自动驱动流程；agent 和分阶段工具会读取它作为复现记录。

   ```bash
   python scripts/manage_project_config.py init "generated_subtitles/<work_id>" \
     --work-id "<work_id>" \
     --project-type with-script \
     --asr-dir "generated_subtitles/<work_id>/<asr_dir>" \
     --zh-srt-dir "generated_subtitles/<work_id>/srt_work" \
     --final-dir "generated_subtitles/<work_id>/<原音频文件夹名>" \
     --promo-asr-dir "generated_subtitles/<work_id>/<promo_asr_dir>" \
     --promo-zh-srt-dir "generated_subtitles/<work_id>/promo_srt_work" \
     --promo-final-dir "generated_subtitles/<work_id>/<原促销音频文件夹名>" \
     --asr-backend auto \
     --output-format vtt \
     --translate-backend auto \
     --translate-model "$TRANSLATE_MODEL" \
     --qc-model "$TRANSLATE_MODEL" \
     --overwrite
   ```

   可随时查看配置摘要：

   ```bash
   python scripts/manage_project_config.py show "generated_subtitles/<work_id>"
   ```

   随后跑一次环境检测，确认脚本、Python 依赖、项目路径、ASR/翻译后端、外部命令和本地翻译 API 状态。默认只报告；如果缺轻量 Python 包，可先 dry-run，再在用户允许时自动安装。API 服务尚未启动时通常只会得到 warning；已有 `.ja.asr.srt` 时，本地 ASR 后端缺失通常不应阻塞翻译/QC/校验；如果本轮需要新跑 ASR，加 `--require-asr` 做更严格检查。

   ```bash
   python scripts/check_environment.py \
     --config "generated_subtitles/<work_id>/project_config.json" \
     --json-out "generated_subtitles/<work_id>/env_report.json"
   ```

   如报告缺少 `tqdm`、`PyYAML` 等轻量 Python 包，可先预览安装命令：

   ```bash
   python scripts/check_environment.py --dry-run-install --skip-api
   ```

   用户允许修改当前 Python 环境时再安装：

   ```bash
   python scripts/check_environment.py --install-missing-python --skip-api
   ```

4. 跑日文 ASR

   若 `project_config.json` 指向的 ASR 目录已经有可用的 `*.ja.asr.srt`，且结构校验通过，可以跳过本步骤，直接进入台本对照或翻译。只有需要新跑 ASR 时，才必须确认当前 ASR 后端可用。若有无 SE 版本且用户没有指定别的版本，优先用无 SE 版本作为 ASR 输入；最终字幕目录仍按目标音频目录命名。

   先设置当前项目使用的模型和输出目录名。下面只是示例，实际可替换：

   ```bash
   export ASR_MODEL="/path/or/hf_repo/of/current_asr_model"
   export ASR_AUDIO_DIR="/path/to/asr_audio_dir"
   export ASR_DIR="generated_subtitles/<work_id>/asr_current"
   export PROMO_ASR_DIR="generated_subtitles/<work_id>/promo_asr_current"
   ```

   单条音频：

   ```bash
   python scripts/transcribe_mlx.py \
     "/path/to/audio.wav" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --language ja
   ```

   批量音频：

   ```bash
   python scripts/batch_transcribe_mlx.py \
     --audio-dir "$ASR_AUDIO_DIR" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --glob "*.wav" \
     --language ja
   ```

5. 台本对照

   - 若台本是 PDF，先抽取文本。
   - 使用 `compare_asr_to_script.py` 生成 ASR 与台本的模糊比对报告。

   ```bash
   python scripts/compare_asr_to_script.py \
     --pdf "/path/to/script.pdf" \
     --asr-dir "$ASR_DIR" \
     --out "generated_subtitles/<work_id>/asr_vs_script_report.md"
   ```

   重点看：

   - ASR 是否和台本大体一致。
   - 哪些低置信片段明显是 ASR 幻觉。
   - 促销/试听音频通常不一定有完整台本，需单独处理。

6. 初翻

   默认使用 `auto` 后端选择：Windows/WSL 优先 Ollama；没有 Ollama 时回退到其他可用 OpenAI-compatible 服务；macOS 可继续优先使用 oMLX 的 OpenAI-compatible 本地 API。先启动当前选择的本地推理服务，再设置当前项目使用的模型和 API 地址：

   ```bash
   # macOS/oMLX 示例：
   # omlx serve --port 8000
   #
   # Windows/WSL/Ollama 示例：
   # ollama serve
   ```

   ```bash
   export TRANSLATE_BASE_URL="http://127.0.0.1:8000/v1"
   export TRANSLATE_MODEL="current-good-omlx-model"
   export TRANSLATE_API_KEY="local-placeholder"
   export ZH_SRT_DIR="generated_subtitles/<work_id>/srt_work"
   export PROMO_ZH_SRT_DIR="generated_subtitles/<work_id>/promo_srt_work"
   export ZH_DIR="generated_subtitles/<work_id>/<原音频文件夹名>"
   export PROMO_ZH_DIR="generated_subtitles/<work_id>/<原促销音频文件夹名>"
   ```

   本篇：

   ```bash
   python scripts/batch_translate_srt_omlx.py \
     --input-dir "$ASR_DIR" \
     --output-dir "$ZH_SRT_DIR" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9
   ```

   促销：

   ```bash
   python scripts/batch_translate_srt_omlx.py \
     --input-dir "$PROMO_ASR_DIR" \
     --output-dir "$PROMO_ZH_SRT_DIR" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9
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
     --chunk-size 9
   ```

7. 结构校验

   每次生成或手修后都要校验：

   - 中文 SRT 与日文 ASR 条目数一致。
   - 每条编号、开始时间、结束时间一致。
   - 无空字幕。
   - 无时间重叠。

   可用校验脚本：

   ```bash
   python scripts/validate_subtitles.py \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --json-out "generated_subtitles/<work_id>/validate_report.json"
   ```

   若有促销/试听音频，使用对应的促销 ASR 目录和促销 SRT 工作目录再跑一次。

   结构校验通过后，做一次 ASMR 可读性检查。该检查只输出 warning，不自动拆字幕、不改时间轴：

   ```bash
   python scripts/subtitle_readability.py \
     "$ZH_SRT_DIR" \
     --max-cps 10 \
     --json-out "generated_subtitles/<work_id>/readability_report.json"
   ```

8. 内容校对

   先自动扫高风险词，再人工通读。

   ```bash
   python scripts/scan_subtitle_risks.py \
     "generated_subtitles/<work_id>" \
     --json-out "generated_subtitles/<work_id>/risk_report.json"
   ```

   默认风险规则文件是 `data/subtitle_risk_patterns.json`。如需测试临时规则，可用 `--rules <rules.json>` 指定。

   如果脚本暂时不可用，可临时用 `rg` 扫语料库中的高风险词，但正式流程优先使用 `scan_subtitle_risks.py`，便于保留报告。

   校对原则：

   - 明显 ASR 错词必须修。
   - 影响剧情、人称、性行为类型、人物关系的错译必须修。
   - 长段重复喘息/拟声可压缩为 `[喘息声]`、`[亲吻声和舔耳声]`、`撸撸……` 等。
   - 台本中长时间连续重复同一拟声词时，不要逐字铺满字幕。短段可保留少量节奏，如 `啾……啾啾……`；超过一条字幕或持续数秒的同类音效，优先压缩成 `[持续亲吻声]`、`[长段舔耳声]`、`[持续摩擦声]`、`[长长的喘息声]`。
   - 校对拟声词时必须对照日文台本或日文 ASR。先判断原文拟声对应的是亲吻、舔耳、手冲摩擦、抽插、喘息还是其他音效，再决定中文提示；不要只根据中文重复字符自行猜音效类型。
   - 如果拟声中夹着有效台词，只压缩纯音效部分，台词必须保留。处理目标是保留 ASMR 氛围，不让字幕变成重复字符墙。
   - 不为了文学性大改原句；保持可读、顺口、贴情境。
   - 手修只改字幕内容，不改时间轴和编号。

9. 台本复核

   有台本时，重点用台本确认：

   - ASR 同音错词。
   - 角色称呼和语气。
   - 轨道之间剧情连续性。
   - 专有设定、人物身份、关系变化。

   不要盲信 ASR；当 ASR 与台本冲突，优先结合台本和上下文判断。模型建议若与台本冲突，默认先视为 QC 误报，除非相邻字幕、音频标题或促销剪辑语境能证明台本不适用于当前音频。

10. 必须模型质检

   在台本复核之后，把日文 ASR 与中文字幕成对喂给当前可用模型，让它只输出明显问题。模型 QC 不替代台本复核，只用于辅助发现人工通读容易漏掉的局部逻辑错位。

   ```bash
   python scripts/qc_srt_omlx.py \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --out "generated_subtitles/<work_id>/qc_report.json" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 18 \
     --context "作品主题、角色关系、台本关键词、已知 ASR 易错词"
   ```

   处理原则：

   - 第一轮模型 QC 后，agent 必须处理 `qc_report.json` 中所有明确问题，并完成一轮修正；这一步不是可选项。
   - agent 处理 QC 建议时，不能仅凭自身模型判断；必须对照日文 ASR、当前中文字幕、相邻字幕、台本和语料库规则。agent 的职责是执行证据驱动的修正流程，而不是凭感觉重翻。
   - `qc_report.json` 中的建议是候选，不可照单全收。修正前回看相邻字幕、台本对应段落和轨道标题；有台本时以台本和上下文为准。
   - 明确正确的建议应修正；明显违背台本或上下文的建议记录为误报，不修改字幕；无法判断的条目标为待复核。
   - 第一轮 QC 修正后必须再跑结构校验、高风险扫描和可读性检查。
   - 如果需要第二轮 QC、仍有待复核条目、模型建议互相冲突，或用户想介入，再生成人工审阅材料。

   需要人工介入时，可生成 QC 审阅模板：

   ```bash
   python scripts/review_qc_report.py \
     "generated_subtitles/<work_id>/qc_report.json" \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --out "generated_subtitles/<work_id>/qc_review.md" \
     --json-out "generated_subtitles/<work_id>/qc_review_items.json"
   ```

   人可以直接基于 `qc_report.json` 提意见，也可以在 `qc_review.md` 中逐条标记 `accept`、`reject` 或 `defer`。`review_qc_report.py` 只生成审阅材料，不自动改字幕。

   如果第一轮强制 QC 和修正后，用户仍觉得台词不满意，把后续处理作为“追加 QC 精修功能”，而不是重做基础流程。每一轮都要有独立目录，避免覆盖第一次 `qc_report.json`：

   ```bash
   python scripts/manage_qc_refinement.py start \
     "generated_subtitles/<work_id>" \
     --mode auto \
     --focus "用户指出的问题类型，例如语气太硬、亲密感不足、某角色称呼不稳"
   ```

   如果用户提供了引导词、风格说明或指出具体翻译问题，使用 guided 模式：

   ```bash
   python scripts/manage_qc_refinement.py start \
     "generated_subtitles/<work_id>" \
     --mode guided \
     --focus "台词精修" \
     --user-guidance "现在太硬了，希望更亲密、更像 ASMR 口语，但不要过度改写"
   ```

   该命令会创建 `generated_subtitles/<work_id>/qc_refinement/round_NN/manifest.json`、`context_profile.md` 和 `next_steps.md`。`context_profile.md` 会记录自动识别到的作品情境、轨道抽样和用户引导。按 `next_steps.md` 执行：重新跑一轮聚焦 QC、生成 review items、由 agent 基于证据标记 `accept/reject/defer`、应用 accepted 项、再跑结构/风险/可读性检查。用户仍不满意时再开下一轮。

   若 agent 已经按证据确认一批明确问题，可直接编辑 `qc_review_items.json`：把明确应修的条目标为 `"decision": "accept"`，必要时把最终译文写入 `"replacement"`；误报标为 `reject`，无法判断标为 `defer`。随后先 dry-run，再正式应用：

   ```bash
   python scripts/apply_qc_decisions.py \
     "generated_subtitles/<work_id>/qc_review_items.json" \
     --zh-dir "$ZH_SRT_DIR" \
     --json-out "generated_subtitles/<work_id>/qc_apply_report.json"
   ```

   ```bash
   python scripts/apply_qc_decisions.py \
     "generated_subtitles/<work_id>/qc_review_items.json" \
     --zh-dir "$ZH_SRT_DIR" \
     --apply \
     --backup-dir "generated_subtitles/<work_id>/qc_apply_backup" \
     --json-out "generated_subtitles/<work_id>/qc_apply_report.json"
   ```

   只允许应用已确认的 `accept` 项；应用后必须再跑结构校验、高风险扫描和可读性检查。

11. 促销/试听单独复查

   促销经常是本篇剪辑或重录，不能假设本篇修过就等于促销也修过。

   - 单独扫促销 SRT 中间目录，例如 `$PROMO_ZH_SRT_DIR`。
   - 单独跑模型质检，或在同一次 QC 中覆盖促销 ASR 与促销字幕目录。
   - 单独打印全文人工读。
   - 单独跑结构校验。

12. 导出 WebVTT

   结构校验、可读性检查、人工修订和模型质检都通过后，按用户选择导出最终字幕。默认把 SRT 中间稿导出为 WebVTT `.zh.vtt`；如果用户要求 `srt`，可直接交付 `.zh.srt`；如果用户要求 `both`，同时交付 `.zh.srt` 和 `.zh.vtt`。

   本篇：

   ```bash
   python scripts/convert_srt_to_vtt.py \
     "$ZH_SRT_DIR" \
     "$ZH_DIR" \
     --glob "*.zh.srt" \
     --overwrite
   ```

   促销：

   ```bash
   python scripts/convert_srt_to_vtt.py \
     "$PROMO_ZH_SRT_DIR" \
     "$PROMO_ZH_DIR" \
     --glob "*.zh.srt" \
     --overwrite
   ```

   导出后确认最终成品目录只包含该音频目录对应的最终字幕格式。默认只放 `.zh.vtt`；用户指定 `srt` 或 `both` 时按选择放置。如需回修，先改 SRT 中间稿并重新校验，再重新导出 VTT。

13. 更新学习库

   每完成一个作品，都要从本次翻译、台本复核、模型 QC、风险扫描、可读性检查和人工修正中提炼可复用经验。不要只记录“做完了”，要把下次能用的东西沉淀下来。

   更新学习库：

   - 每个完成的作品都必须在 `references/project-lessons.md` 追加项目记录。
   - 新术语写入 `references/terms.md`。
   - 本作设定下更自然且可复用的译法和字幕风格规则写入 `references/style.md`。
   - ASR 易错词、常见误译和误报说明写入 `references/risk-notes.md`。
   - 本次踩坑和项目级修正例写入 `references/project-lessons.md`。
   - 记录来源作品、轨道、日期、是否有台本。

   同时整理风险库候选：

   - 从 `qc_report.json` 中提取确认过的 ASR 错词和翻译雷区。
   - 从 `risk_report.json` 中区分真阳性、误报和需要收窄的规则。
   - 从最终手修中提取可机械扫描的高风险词或短语。
   - 可机械扫描的确认规则写入 `data/subtitle_risk_patterns.json`；`references/risk-notes.md` 保留上下文、来源和适用条件。
   - 不确定条目写入 `references/pending.md` 并标 `待验证`，不要写成定论。

   可先生成学习库更新草稿：

   ```bash
   python scripts/update_learning_library.py \
     "generated_subtitles/<work_id>" \
     --out "generated_subtitles/<work_id>/learning_update.md"
   ```

   确认内容后，可追加项目经验骨架，再把可复用内容手动同步到对应 reference：

   ```bash
   python scripts/update_learning_library.py \
     "generated_subtitles/<work_id>" \
     --append-project-lesson
   ```

## 交付清单

- 告知用户成品路径。
- 说明本篇与促销是否都完成。
- 说明结构校验结果。
- 说明最终字幕格式：默认 WebVTT `.vtt`，或用户指定的 `.srt` / `both`。
- 说明模型质检是否完成，`qc_report.json` 路径在哪里。
- 说明 `project_config.json` 路径和最终 `output_format`。
- 说明本次新增了哪些语料库/风险库经验，或说明没有发现值得沉淀的新规则。
- 简述修过的主要问题类型。
- 如有无法确认的句子，列出文件名和编号，不要假装确定。
