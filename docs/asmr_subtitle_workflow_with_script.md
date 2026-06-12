# 有对照台本的 ASMR 烤肉工作流

适用场景：作品文件夹内有官方台本、初稿台本、PDF、TXT、HTML、字幕文本或类似可对照文本，需要为每条音频生成单独可挂载的简体中文字幕。

本工作流基于 `RJ01201653` 的实践整理。执行前先阅读并参考 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)，完成后把新学到的术语、错词和风格规则追加回语料库。

## 目标

- 每条音频生成独立中文字幕；工作中间格式可继续使用 `.zh.srt`，最终交付给 DLsite 音声项目时应导出为 WebVTT，即 `.zh.vtt`。
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
- 中文本篇字幕：`generated_subtitles/<work_id>/<原音频文件夹名>/*.zh.vtt`
- 促销 SRT 中间稿：`generated_subtitles/<work_id>/promo_srt_work/*.zh.srt`
- 促销字幕：`generated_subtitles/<work_id>/<原促销音频文件夹名>/*.zh.vtt`
- 可选比对报告：`generated_subtitles/<work_id>/asr_vs_script_report.md`

字幕成品目录必须与原始音频目录同名。若原始作品内有 `WAV 本編/`、`プロモーション用音声/`、`音声/` 等音频文件夹，输出目录中也建立同名文件夹，只放该文件夹音源对应的 `.zh.vtt`。ASR、SRT 中间稿、QC 报告、review notes 等工作产物留在作品输出根目录或专用工作目录中，不与成品字幕混放。

DLsite 音声自带字幕常见格式是 WebVTT。除非用户明确要求 SRT，后续工程的最终导出格式统一按 `.vtt` 处理；`.srt` 只作为 ASR、翻译、校验和手修阶段的中间格式。

## 工具选择原则

工具和模型不是流程的一部分，只是实现手段。每次开工时先确认当前机器上可用的 ASR、翻译后端、模型路径和 API 地址，再选择“当下效果最好且速度可接受”的组合。

如果使用第三方平台或本地推理服务，比如 oMLX、LM Studio 或类似工具，优先走它们官方提供的调用接口。若该平台提供的是 OpenAI-compatible API，就优先直接调用这套接口，而不是通过间接包装、非官方桥接或界面自动化去调用。端口也优先采用平台官方默认端口；只有在默认端口被占用、服务不可用或平台明确要求时，才改用其他端口。这样更容易：

- 观察模型是否真的在运行。
- 查看实际占用的端口、请求和日志。
- 排查失败是出在模型、服务还是脚本。
- 保持脚本、监控和后续排障方式一致。
- 尽量减少“同一工具在不同端口间漂移”带来的混淆。

本次 `RJ01201653` 的可用组合仅作为示例：

- ASR 示例：`mlx-community/whisper-large-v3-mlx-4bit`
- ASR 模型路径示例：`~/.lmstudio/models/mlx-community/whisper-large-v3-mlx-4bit`
- 默认翻译后端：oMLX 的 OpenAI-compatible 本地 API。LM Studio、本机其他推理服务或云端模型仅作为 oMLX 不可用时的备用方案。
- 翻译模型示例：`Qwen3.6-27B-MLX-VL-oQ6`
- 依赖示例：`srt`, `mlx_whisper`, `pdftotext`

替换原则：

- ASR 可以换成更强 Whisper、WhisperX、其他日语 ASR 或云端 ASR，只要输出可解析的日文 SRT/JSON。
- 翻译模型默认走 oMLX 当前可用的高质量日译中模型；如需更换成本地其他后端或云端模型，必须仍能稳定按编号返回中文字幕。
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

2. 读取语料库

   - 先读 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)。
   - 记录本作设定：人物称呼、敬语程度、角色关系、关键术语。
   - 本作若有专有词，先建立临时术语表，翻译结束后整理进语料库。

3. 跑日文 ASR

   先设置当前项目使用的模型和输出目录名。下面只是示例，实际可替换：

   ```bash
   export ASR_MODEL="/path/or/hf_repo/of/current_asr_model"
   export ASR_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/asr_current"
   export PROMO_ASR_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/promo_asr_current"
   ```

   单条音频：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/transcribe_mlx.py \
     "/path/to/audio.wav" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --language ja
   ```

   批量音频：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/batch_transcribe_mlx.py \
     --audio-dir "/path/to/audio_dir" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --glob "*.wav" \
     --language ja
   ```

4. 台本对照

   - 若台本是 PDF，先抽取文本。
   - 使用 `compare_asr_to_script.py` 生成 ASR 与台本的模糊比对报告。

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/compare_asr_to_script.py \
     --pdf "/path/to/script.pdf" \
     --asr-dir "$ASR_DIR" \
     --out "/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/asr_vs_script_report.md"
   ```

   重点看：

   - ASR 是否和台本大体一致。
   - 哪些低置信片段明显是 ASR 幻觉。
   - 促销/试听音频通常不一定有完整台本，需单独处理。

5. 初翻

   默认使用 oMLX。先启动 oMLX OpenAI-compatible 服务，再设置当前项目使用的模型和 API 地址：

   ```bash
   omlx serve --port 8000
   ```

   ```bash
   export TRANSLATE_BASE_URL="http://127.0.0.1:8000/v1"
   export TRANSLATE_MODEL="current-good-omlx-model"
   export TRANSLATE_API_KEY="local-placeholder"
   export ZH_SRT_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/srt_work"
   export PROMO_ZH_SRT_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/promo_srt_work"
   export ZH_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/<原音频文件夹名>"
   export PROMO_ZH_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/<原促销音频文件夹名>"
   ```

   本篇：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/batch_translate_srt_omlx.py \
     --input-dir "$ASR_DIR" \
     --output-dir "$ZH_SRT_DIR" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9
   ```

   促销：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/batch_translate_srt_omlx.py \
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
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/translate_srt_omlx.py \
     "$ASR_DIR/<file>.ja.asr.srt" \
     "$ZH_SRT_DIR/<file>.zh.srt" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 9
   ```

6. 结构校验

   每次生成或手修后都要校验：

   - 中文 SRT 与日文 ASR 条目数一致。
   - 每条编号、开始时间、结束时间一致。
   - 无空字幕。
   - 无时间重叠。

   可用校验脚本：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs python3 - <<'PY'
   import os, srt, pathlib
   base=pathlib.Path('/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>')
   pairs=[(pathlib.Path(os.environ['ASR_DIR']), pathlib.Path(os.environ['ZH_SRT_DIR']))]
   if os.environ.get('PROMO_ASR_DIR'):
       pairs.append((pathlib.Path(os.environ['PROMO_ASR_DIR']), pathlib.Path(os.environ['PROMO_ZH_SRT_DIR'])))
   ok=True
   for asr, zhdir in pairs:
       if not asr.exists() or not zhdir.exists():
           continue
       for ja in sorted(asr.glob('*.ja.asr.srt')):
           zh=zhdir/(ja.name.replace('.ja.asr.srt','.zh.srt'))
           ja_subs=list(srt.parse(ja.read_text(encoding='utf-8')))
           zh_subs=list(srt.parse(zh.read_text(encoding='utf-8')))
           same=len(ja_subs)==len(zh_subs) and all(a.index==b.index and a.start==b.start and a.end==b.end for a,b in zip(ja_subs,zh_subs))
           overlaps=sum(1 for i in range(len(zh_subs)-1) if zh_subs[i].end>zh_subs[i+1].start)
           empty=[x.index for x in zh_subs if not x.content.strip()]
           print(f'{zh.name}: same={same} count={len(zh_subs)} overlaps={overlaps} empty={empty}')
           ok = ok and same and not overlaps and not empty
   print('VALIDATION', 'OK' if ok else 'FAILED')
   PY
   ```

7. 内容校对

   先自动扫高风险词，再人工通读。

   ```bash
   rg -n "感谢.*观看|订阅|语言模型|JSON|undefined|null|正义|冥想|写生|魔女|警察|生涩|手呼吸|耳舐|嘘嘘|尿尿|道谢|草子|大开杀戒|Love Hotel|我的Cosplay" \
     "/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>"
   ```

   校对原则：

   - 明显 ASR 错词必须修。
   - 影响剧情、人称、性行为类型、人物关系的错译必须修。
   - 长段重复喘息/拟声可压缩为 `[喘息声]`、`[亲吻声和舔耳声]`、`撸撸……` 等。
   - 台本中长时间连续重复同一拟声词时，不要逐字铺满字幕。短段可保留少量节奏，如 `啾……啾啾……`；超过一条字幕或持续数秒的同类音效，优先压缩成 `[持续亲吻声]`、`[长段舔耳声]`、`[持续摩擦声]`、`[长长的喘息声]`。
   - 校对拟声词时必须对照日文台本或日文 ASR。先判断原文拟声对应的是亲吻、舔耳、手冲摩擦、抽插、喘息还是其他音效，再决定中文提示；不要只根据中文重复字符自行猜音效类型。
   - 如果拟声中夹着有效台词，只压缩纯音效部分，台词必须保留。处理目标是保留 ASMR 氛围，不让字幕变成重复字符墙。
   - 不为了文学性大改原句；保持可读、顺口、贴情境。
   - 手修只改字幕内容，不改时间轴和编号。

8. 台本复核

   有台本时，重点用台本确认：

   - ASR 同音错词。
   - 角色称呼和语气。
   - 轨道之间剧情连续性。
   - 专有设定、人物身份、关系变化。

   不要盲信 ASR；当 ASR 与台本冲突，优先结合台本和上下文判断。模型建议若与台本冲突，默认先视为 QC 误报，除非相邻字幕、音频标题或促销剪辑语境能证明台本不适用于当前音频。

9. 必须模型质检

   在台本复核之后，把日文 ASR 与中文字幕成对喂给当前可用模型，让它只输出明显问题。模型 QC 不替代台本复核，只用于辅助发现人工通读容易漏掉的局部逻辑错位。

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs:/Users/someone_tokki/Program/CodeX/Asmr/tools \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/qc_srt_omlx.py \
     --asr-dir "$ASR_DIR" \
     --zh-dir "$ZH_SRT_DIR" \
     --out "/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/qc_report.json" \
     --api-key "$TRANSLATE_API_KEY" \
     --base-url "$TRANSLATE_BASE_URL" \
     --model "$TRANSLATE_MODEL" \
     --chunk-size 18 \
     --context "作品主题、角色关系、台本关键词、已知 ASR 易错词"
   ```

   处理原则：

   - `qc_report.json` 中的建议是候选，不可照单全收。
   - 改动前回看相邻字幕、台本对应段落和轨道标题；有台本时以台本和上下文为准。
   - 批量套用建议后必须再跑结构校验和高风险词扫描。
   - 若模型建议明显违背台本或上下文，记录为误报，不要修改字幕。

10. 促销/试听单独复查

   促销经常是本篇剪辑或重录，不能假设本篇修过就等于促销也修过。

   - 单独扫促销 SRT 中间目录，例如 `$PROMO_ZH_SRT_DIR`。
   - 单独跑模型质检，或在同一次 QC 中覆盖促销 ASR 与促销字幕目录。
   - 单独打印全文人工读。
   - 单独跑结构校验。

11. 导出 WebVTT

   结构校验、人工修订和模型质检都通过后，把 SRT 中间稿导出为最终交付用 WebVTT。DLsite 音声项目默认交付 `.zh.vtt`；除非用户明确要求，不再把 `.zh.srt` 放进最终成品目录。

   本篇：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/convert_srt_to_vtt.py \
     "$ZH_SRT_DIR" \
     "$ZH_DIR" \
     --glob "*.zh.srt" \
     --overwrite
   ```

   促销：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/convert_srt_to_vtt.py \
     "$PROMO_ZH_SRT_DIR" \
     "$PROMO_ZH_DIR" \
     --glob "*.zh.srt" \
     --overwrite
   ```

   导出后确认最终成品目录只包含该音频目录对应的 `.zh.vtt`。如需回修，先改 SRT 中间稿并重新校验，再重新导出 VTT。

12. 更新语料库

   完成后更新 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)：

   - 新术语。
   - 本作设定下更自然的译法。
   - ASR 易错词。
   - 本次踩坑和修正例。
   - 记录来源作品、轨道、日期、是否有台本。

## 交付清单

- 告知用户成品路径。
- 说明本篇与促销是否都完成。
- 说明结构校验结果。
- 说明最终字幕已导出为 WebVTT `.vtt`。
- 说明模型质检是否完成，`qc_report.json` 路径在哪里。
- 简述修过的主要问题类型。
- 如有无法确认的句子，列出文件名和编号，不要假装确定。
