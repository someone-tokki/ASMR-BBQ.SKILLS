# ASMR 字幕任务分流规则

用途：开工前先判断当前请求属于哪条路线，再读取对应 workflow 和参考资料。agent 负责分流；脚本只做检查、报告、转换和可重复步骤。

## 分流原则

- 先盘点输入：音频、官方台本/初稿/PDF/TXT/HTML、已有 `.ja.asr.srt`、已有 `.zh.srt`/`.zh.vtt`、促销/试听目录、用户要求的输出格式。
- 若音频包里同时存在有 SE/无 SE 版本，默认优先用无 SE 版本跑 ASR；如果用户明确指定要用其他版本，则用户指定优先。
- 默认最终输出为 `.zh.vtt`；用户可明确选择 `srt` 或 `both`。`.zh.srt` 默认仍是工作中间稿。
- 不因为当前机器不能新跑 ASR 就阻塞已有 ASR 项目的翻译、QC、风险扫描、可读性检查和导出。
- 每条路线都必须在交付前完成结构校验、风险扫描、ASMR 可读性检查、第一轮强制模型 QC 和学习库更新，除非用户明确只要求一个只读检查或格式转换。

## 路线表

| 输入状态 | 路线 | 首要动作 | 必读文件 | 必做检查 |
| --- | --- | --- | --- | --- |
| 有音频和可用台本/文本 | 有台本完整流程 | 建立 `project_config.json`，跑或复用 JA ASR，再做台本对照 | `docs/asmr_subtitle_workflow_with_script.md`、`references/style.md`、`references/terms.md` | `validate_subtitles.py`、`scan_subtitle_risks.py`、`subtitle_readability.py`、强制 QC |
| 只有音频，无可用台本 | 无台本完整流程 | 建立配置，确认 ASR 后端；若已有 JA ASR 可跳过新 ASR | `docs/asmr_subtitle_workflow_no_script.md`、`references/style.md`、`references/terms.md`、`references/risk-notes.md` | 结构、风险、可读性、强制 QC；必要时听感抽检 |
| 已有 `.ja.asr.srt`，还没有中文字幕 | 复用 ASR 翻译路线 | 先校验 JA ASR 结构；环境检测不加 `--require-asr` | 按是否有台本选择 workflow | 与完整流程相同，但可跳过新 ASR |
| 已有 `.zh.srt` 工作稿 | QC/修正路线 | 成对校验 JA ASR 与 ZH SRT；跑风险、可读性和 QC | 对应 workflow、`references/risk-notes.md` | 修正明确 QC 问题后重跑结构、风险、可读性 |
| 已有最终 `.zh.vtt` 或 `.zh.srt` | 复查/再交付路线 | 找到对应工作稿；若没有工作稿，先决定是否从最终文件回建检查输入 | `references/style.md`、`references/risk-notes.md` | 至少风险和可读性；能成对时跑结构和 QC |
| 只要求 SRT/VTT 转换 | 格式转换路线 | 确认源字幕结构 OK，再按 `output_format` 导出 | `docs/task_routing.md`、必要时 workflow 导出段 | `validate_subtitles.py --final-dir` 或源目录结构检查；确认成品目录无中间产物 |
| 只要求扫描/审阅 | 只读检查路线 | 不修改字幕；生成报告并总结问题 | `references/risk-notes.md`、`references/style.md` | 按请求跑结构、风险、可读性或 QC 审阅模板 |
| 促销/试听音频存在 | 促销并行子路线 | 为促销建立独立 ASR/SRT 工作目录和同名最终目录 | 对应 workflow 的促销段 | 促销单独结构、风险、可读性、QC，不复用本篇结论 |

## 开工步骤

1. 识别 `work_id`、源音频目录、促销/试听目录、台本状态、已有 ASR/中文字幕状态和输出格式。
2. 如果识别到 RJ 号且允许联网，先用 `scripts/fetch_dlsite_work_info.py` 抓取 DLsite 商品页元信息，保存到 `generated_subtitles/<work_id>/dlsite_work_info.json`。抓取失败不阻塞流程。
3. 新跑 ASR 前，用 `scripts/select_asr_audio_source.py` 扫音频版本；无 SE 只是默认推荐，用户指定版本时用用户指定。
4. 读取 `docs/asmr_translation_corpus.md`，再按任务读取它指向的 reference。
5. 按路线读取有台本或无台本 workflow。
6. 创建或更新 `generated_subtitles/<work_id>/project_config.json`。
7. 跑 `scripts/check_environment.py`；只有本轮必须新跑 ASR 时才加 `--require-asr`。
8. 进入对应 workflow 的执行步骤。

## 模型任务边界

- ASR/转文字任务：只负责从音频生成日文 `.ja.asr.srt`/JSON，不负责最终翻译判断。
- 翻译模型任务：负责把日文 ASR 或台本辅助下的日文字幕翻成 `.zh.srt`，必须保持编号和时间轴。
- QC 模型任务：只产出候选问题和建议，不直接改字幕；第一轮 QC 必跑。
- Agent 任务：分流、读 reference、调用脚本、证据驱动地修正字幕、复跑检查、更新学习库和交付说明。

## 人工介入

人工审阅不强制。第一轮模型 QC 后，agent 必须处理所有明确问题并重跑检查；只有第二轮 QC、未决问题、冲突建议或用户主动要求时，才生成人工审阅材料或等待用户意见。
