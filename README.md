# ASMR-BBQ.SKILLS

这是一个面向简体中文 ASMR 字幕工作的 Skill 项目，主要服务于日文 ASMR / 同人音声的翻译、校对、质检、导出和学习回收。

它适合做这些事：

- 扫描 RJ 作品目录里的音频范围；
- 复用或创建日文 ASR 字幕；
- 把日文 ASMR 字幕翻成自然的简体中文；
- 维持术语、语气和 ASMR 可读性一致；
- 跑强制模型 QC 和风险检查；
- 导出最终 `.zh.vtt` 或 `.zh.srt`；
- 保留中间产物，方便续跑、复核和学习整理。

## 入口

Skill 的入口文件是 [SKILL.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/SKILL.md)。目前的工作流是：

1. 先读 `SKILL.md`。
2. 再读 `docs/task_routing.md` 和对应的工作流文档。
3. 然后调用 `scripts/` 里的脚本完成流程。

计划中的独立 CLI 入口写在 [docs/cli_design.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/cli_design.md)。

```bash
python scripts/asmr_bbq.py status /path/to/RJxxxxxx
python scripts/asmr_bbq.py run /path/to/RJxxxxxx --interactive
```

在这个 CLI 真正存在之前，直接按照 Skill 文档里的脚本流程执行。

## 输出结构

默认情况下，项目文件会放在源音声目录里：

```text
RJ012345/
  subtitle_project/   # ASR、SRT 工作文件、run profile、QC、报告、学习草稿
  subtitles/          # 最终 .zh.vtt / .zh.srt 交付文件
```

`subtitle_project/` 放可恢复的工作产物，`subtitles/` 只放最终交付字幕。

## 本机共享状态

已安装的 Skill 包在普通字幕工作中按只读使用。用户级状态放在 Skill 包外面，这样同一台机器上的多个本地 agent 可以共享。

```text
~/ASMR-Subtitle-Translator/
  learning/           # 共享学习库和 review 队列
  asr/                # 共享 Python Whisper 虚拟环境和模型缓存
```

可以用环境变量覆盖默认位置：

```bash
ASMR_SUBTITLE_LEARNING_DIR=/path/to/learning
ASMR_SUBTITLE_ASR_DIR=/path/to/asr
```

## 质量规则

- 保持 SRT 编号、顺序、开始时间、结束时间稳定，除非明确要重定时。
- 翻译必须覆盖所有目标字幕编号。
- 模型 QC 的建议只是候选证据，不会自动改字幕。
- `draft` 可以快，但不能假装成精品质量。
- 项目发现不会自动晋升到共享语料库。

## Shared Corpus Review

收尾时，agent 会先问你还有没有要修正的地方，以及要不要现在整理学习库。  
如果你选择整理学习库，它会继续问你要走哪一种：

```text
1. 让 agent 协助做 shared corpus review；
2. 先把项目加到 review 队列，之后你自己审；
3. 跳过这次 shared corpus review。
```

只有你明确 `approve` 的条目，才会迁移到共享的用户学习库。项目级、证据不足、只适用于单作设定的内容，会留在 `$PROJECT_ROOT/learning/`。

处理完当前项目后，agent 会再看一次 review 队列。如果里面已经有待审 packet，它会提醒你现在要不要顺手处理。

查看 review 队列：

```bash
python scripts/manage_shared_corpus_review.py \
  --list-queue \
  --json-out "$PROJECT_ROOT/learning/review_queue_status.json"
```

只迁移已 approve 的候选：

```bash
python scripts/manage_shared_corpus_review.py \
  --apply-approved \
  --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"
```

## 文档

- [docs/task_routing.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/task_routing.md): 选择正确的工作流。
- [docs/preflight_confirmation.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/preflight_confirmation.md): 模型调用前需要的确认。
- [docs/asmr_subtitle_workflow_with_script.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/asmr_subtitle_workflow_with_script.md): 有台本时的流程。
- [docs/asmr_subtitle_workflow_no_script.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/asmr_subtitle_workflow_no_script.md): 只有音频时的流程。
- [docs/learning_library_guide.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/learning_library_guide.md): 学习库和 shared corpus review 规则。
- [docs/platform_compatibility.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/platform_compatibility.md): 后端和平台规则。
- [docs/cli_design.md](/Users/someone_tokki/.codex/worktrees/765b/Asmr/docs/cli_design.md): 规划中的一键 CLI 设计。
