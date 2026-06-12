# 无对照台本的 ASMR 烤肉工作流

适用场景：作品只有音频，没有官方台本、初稿台本或可用文本。目标仍是为每条音频生成独立、可挂载、自然可读的简体中文字幕。

开始前必须阅读 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)。完成后把新发现的术语、错词和风格规则追加回语料库，并注明“无台本验证”。

## 核心原则

- 无台本时，ASR 是字幕时间轴和原文的主要来源，但不能盲信。
- 使用当前可用的较好 ASR 方案和更严格的人工校对；模型可替换。
- 不能确认的句子要标为待复核或向用户说明，不要编剧情。
- 促销/试听也要单独跑、单独校对。
- 中文质量目标与有台本项目相同：自然、有人情味、符合情境，不生硬直译。
- 长时间 ASR/翻译任务应使用脚本侧进度条；正常推进时少打扰用户，只有报错、需要决策或阶段完成时再单独说明。
- 模型质检是必经步骤，不是可选项。无台本项目尤其容易出现“单句看似通顺、整段逻辑跑偏”的错译，必须用模型对照日文 ASR 和中文字幕做一轮候选问题扫描。

如果使用第三方平台或本地推理服务，比如 oMLX、LM Studio 或类似工具，优先走它们官方提供的调用接口。若该平台提供的是 OpenAI-compatible API，就优先直接调用这套接口，而不是通过间接包装、非官方桥接或界面自动化去调用。端口也优先采用平台官方默认端口；只有在默认端口被占用、服务不可用或平台明确要求时，才改用其他端口。这样更容易观察模型运行状态，也更方便看端口、请求和日志，出了问题时能更快判断是模型、服务还是脚本本身。

## 推荐输出结构

```text
generated_subtitles/<work_id>/
  <asr_dir>/
    <track>.ja.asr.json
    <track>.ja.asr.srt
  srt_work/
    <track>.zh.srt
  <原音频文件夹名>/
    <track>.zh.vtt
  <promo_asr_dir>/
    <promo>.ja.asr.json
    <promo>.ja.asr.srt
  promo_srt_work/
    <promo>.zh.srt
  <原促销音频文件夹名>/
    <promo>.zh.vtt
  review_notes.md
```

字幕成品目录必须与原始音频目录同名。若原始作品内有 `音声/`、`WAV 本編/`、`プロモーション用音声/` 等音频文件夹，输出目录中也建立同名文件夹，只放该文件夹音源对应的 `.zh.vtt`。ASR、SRT 中间稿、QC 报告、review notes 等工作产物留在作品输出根目录或专用工作目录中，不与成品字幕混放。

DLsite 音声自带字幕常见格式是 WebVTT。除非用户明确要求 SRT，后续工程的最终导出格式统一按 `.vtt` 处理；`.srt` 只作为 ASR、翻译、校验和手修阶段的中间格式。

## 执行步骤

1. 盘点音频和元信息

   - 列出音频文件、标题、时长、目录结构。
   - 根据文件名判断剧情顺序、本篇、EX、促销。
   - 若有 DLsite 商品页文本、标题、角色介绍、试听说明，可作为低强度上下文参考，但不要当完整台本。

2. 读取语料库

   - 先读 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)。
   - 记录本作初始术语：角色称呼、关系、场景、性行为词、音效偏好。

3. 使用高质量 ASR

   无台本时优先使用当前机器上“识别日语耳语最好”的 ASR。`mlx-community/whisper-large-v3-mlx-4bit` 只是本次可用示例，不是固定要求。如果音频很难、耳语很多、BGM 大，可考虑：

   - 保留 `language=ja`
   - 关闭 `condition_on_previous_text`
   - 使用初始提示说明“成人向日语 ASMR，耳语、吐息、拟声多”
   - 对特别难的音频分段重跑或换更强模型

   设置当前 ASR：

   ```bash
   export ASR_MODEL="/path/or/hf_repo/of/current_asr_model"
   export ASR_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/asr_current"
   ```

   批量命令：

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/batch_transcribe_mlx.py \
     --audio-dir "/path/to/audio_dir" \
     --out-dir "$ASR_DIR" \
     --model "$ASR_MODEL" \
     --glob "*.wav" \
     --language ja
   ```

4. ASR 自检

   无台本时，翻译前先检查日文 ASR：

   - 是否出现明显幻觉：`ご視聴ありがとうございました`、`チャンネル登録`、非剧情广告语。
   - 是否大量漏掉耳语或把拟声识别成普通词。
   - 是否把连续音效识别成长串无意义文本。
   - 标题里的关键词是否在 ASR 中被识别正确。

   记录到 `review_notes.md`：

   - 低置信轨道。
   - 明显要人工注意的时间点。
   - 推测术语和角色关系。

5. 初翻

   默认使用 oMLX 的 OpenAI-compatible 本地 API。只有 oMLX 不可用时，才退到 LM Studio、本地其他 OpenAI-compatible 服务或云端模型。无台本时建议更小 chunk，例如 6 到 9 条，降低上下文丢失和 JSON 出错风险。

   先启动 oMLX，再设置当前翻译后端：

   ```bash
   omlx serve --port 8000
   ```

   ```bash
   export TRANSLATE_BASE_URL="http://127.0.0.1:8000/v1"
   export TRANSLATE_MODEL="current-good-omlx-model"
   export TRANSLATE_API_KEY="local-placeholder"
   export ZH_SRT_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/srt_work"
   export ZH_DIR="/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>/<原音频文件夹名>"
   ```

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

   每次翻译和手修后都必须确认：

   - 中文 SRT 与日文 ASR 条目数一致。
   - 编号、开始时间、结束时间一致。
   - 无空字幕。
   - 无时间重叠。

7. 无台本内容校对

   先扫高风险词：

   ```bash
   rg -n "感谢.*观看|订阅|字幕|语言模型|JSON|undefined|null|正义|冥想|写生|魔女|警察|生涩|手呼吸|耳舐|嘘嘘|尿尿|道谢|草子|大开杀戒|Love Hotel|我的Cosplay" \
     "/Users/someone_tokki/Program/CodeX/Asmr/generated_subtitles/<work_id>"
   ```

   再人工通读。无台本时要特别注意：

   - 前后剧情是否连贯。
   - 人称是否稳定。
   - 同一术语是否前后统一。
   - 音效段是否被误译成台词。
   - ASR 是否把 `シコ/しっこ`、`精液`、`童貞喪失` 等识别错。
   - 长时间连续重复的拟声是否被压缩到可读长度。短段拟声可保留少量节奏，例如 `啾……啾啾……`、`嗯、嗯……哈啊……`；持续数秒或跨多条字幕的同类音效，优先写成 `[持续亲吻声]`、`[长段舔耳声]`、`[持续摩擦声]`、`[长长的喘息声]`。
   - 校对拟声词时必须对照日文 ASR；如果有外部说明或后续取得台本，也要一并对照。先判断原文拟声对应的是亲吻、舔耳、手冲摩擦、抽插、喘息还是其他音效，再决定中文提示；不要只看中文重复字符自行猜音效类型。
   - 拟声中夹着有效台词时，只压缩纯音效部分，保留实际台词；不要因为压缩音效而删掉剧情信息。

8. 必须模型质检

   把日文 ASR 和中文字幕成对喂给当前可用模型，让它只输出“明显问题”，不要让它大面积改风格。无台本项目必须至少跑一轮完整模型质检；若后续批量接受建议或大幅手修，还要再跑一次高风险词扫描和结构校验。

   推荐使用脚本：

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
     --context "作品主题、角色关系、标题关键词、已知 ASR 易错词"
   ```

   推荐质检提示：

   ```text
   你是日译中 ASMR 字幕质检员。检查同编号日文 ASR 与中文字幕。
   只标出明显问题：错译、ASR 误识别导致中文荒唐、残留日文/英文混杂、不符合上下文、中文很不自然。
   不要挑风格小毛病；如果可接受就不要输出。
   输出 JSON 数组，每项 {"i":编号,"problem":"简短说明","suggest":"建议改成的中文字幕"}。
   ```

   注意：

   - 模型质检只能作为候选，不可照单全收。
   - 长文件要小分块，避免模型卡住或上下文漂移。
   - 确定修改前要回看相邻字幕和音轨标题。
   - 批量套用建议后必须人工抽查模型建议本身；模型有时会把生硬但可理解的句子改成更离谱的内容。
   - 对“ASR 高频同音错词”要按整部作品统一扫一遍，不能只改单个命中。例如 `射精` 可能被识别成 `写真/书生`，`オナニー` 可能被识别成 `オーナー`。

9. 听感抽检

   无台本项目建议至少抽检：

   - 每条音频开头 1 到 2 分钟。
   - 每条音频高潮/高密度拟声段。
   - 每条音频结尾。
   - 所有被高风险扫描命中的位置。

   如果用户允许，可打开音频播放器或用本机工具抽听。无法抽听时，在交付时说明“未进行听感抽检”。

10. 促销/试听处理

   - 促销音频单独 ASR、单独翻译、单独校对。
   - 不要简单复制本篇字幕，因为促销可能剪辑、重录、删改句子。
   - 促销更容易有截断句，要让中文可读，但不要补不存在的剧情。

11. 导出 WebVTT

   结构校验、人工修订、模型质检和必要抽听都通过后，把 SRT 中间稿导出为最终交付用 WebVTT。DLsite 音声项目默认交付 `.zh.vtt`；除非用户明确要求，不再把 `.zh.srt` 放进最终成品目录。

   ```bash
   PYTHONPATH=/Users/someone_tokki/Program/CodeX/Asmr/.codex_deps/asmr_subs \
   python3 /Users/someone_tokki/Program/CodeX/Asmr/tools/convert_srt_to_vtt.py \
     "$ZH_SRT_DIR" \
     "$ZH_DIR" \
     --glob "*.zh.srt" \
     --overwrite
   ```

   若有促销/试听音频，使用对应的 `promo_srt_work` 和原促销音频同名目录再导出一次。导出后确认最终成品目录只包含该音频目录对应的 `.zh.vtt`。如需回修，先改 SRT 中间稿并重新校验，再重新导出 VTT。

12. 更新语料库

   完成后更新 [asmr_translation_corpus.md](/Users/someone_tokki/Program/CodeX/Asmr/docs/asmr_translation_corpus.md)：

   - 标明来源为“无台本”。
   - 对不确定术语写“待验证”。
   - 对确认的 ASR 错词写入高风险清单。
   - 如果后续拿到台本，回头验证并把条目标为“已验证”。

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
- 最终字幕是否已导出为 WebVTT `.vtt`。
- 是否有促销。
- 模型质检是否完成，`qc_report.json` 路径在哪里。
- 是否做了听感抽检。
- 有哪些未能完全确认的句子或轨道。
- 语料库是否已更新。
