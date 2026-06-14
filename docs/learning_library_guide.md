# 学习库维护说明

这份文档说明 ASMR Subtitle Translator 的“学习功能”如何使用和维护。这里的学习不是训练模型，而是把每个项目中确认过的经验沉淀到可读、可复查、可被脚本扫描的资料库里，让后续翻译和 QC 更稳定。

## 学习库是什么

学习库分成三层：

- Skill 内置基础库：`references/` 和 `data/subtitle_risk_patterns.json`。这是包内默认规则，只读，不作为长期个人记忆。
- 用户长期学习库：`${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/`。这里保存跨作品可复用的确认经验，默认放在用户家目录下，方便同一台机器上其他安装了本 Skill 的 agent 共用；它不应被 Git pull 或重新安装 Skill 覆盖。
- 单作品工作记录：`$PROJECT_ROOT/learning/`。这里只保存这一个作品的回收记录、候选和中转草稿，作品结束后可以随项目一起归档或移走。

## 什么时候更新

每个作品交付前都要做一次学习库回收。主要来源包括：

- 最终 `.zh.srt` / `.zh.vtt`
- `qc_report.json` 和追加 QC refinement 报告
- `risk_report.json`
- `readability_report.json`
- `validate_report.json`
- 用户人工反馈
- agent 接受、拒绝、推迟的 QC 建议
- 台本复核记录、抽听记录、DLsite 元信息带来的低强度上下文

如果本轮只是只读扫描或中途暂停，可以只写 work record 或 `pending.md`；不要把未完成判断写成全局规则。

## 写入分流

先问这个经验属于哪一类：

| 经验类型 | 写入位置 | 例子 |
| --- | --- | --- |
| 只对本作品成立 | `$PROJECT_ROOT/learning/work_record.md` | 本作姐姐角色固定称呼男主为“你这孩子” |
| 可复用风格 | 用户长期库 `references/style.md` | 长段亲吻声可压缩为可读提示，不逐音节刷屏 |
| 稳定术语 | 用户长期库 `references/terms.md` | `オナサポ` 译为“自慰辅助/自慰陪伴”，不混同 `フェラ` |
| 人读易错说明 | 用户长期库 `references/risk-notes.md` | `そうろう` 易被 ASR 识别成 `僧侶/騒動` |
| 脚本可扫风险 | 用户长期库 `data/subtitle_risk_patterns.local.json` | 正则或固定词命中 `僧侶` 时提示检查是否为 `早漏` |
| 证据不足 | 用户长期库 `references/pending.md` 或 `$PROJECT_ROOT/learning/pending.md` | 无台本且未抽听，只怀疑某词是 ASR 幻觉 |

同一个发现可以写入多个地方。例如一个确认的 ASR 错词，解释写进用户长期 `risk-notes.md`，机械扫描词写进用户长期 `subtitle_risk_patterns.local.json`，本次工作记录写进 `work_record.md`。

## 证据等级

写入前按证据强度分类：

- `confirmed`：台本、日文 ASR、相邻上下文、用户反馈或抽听能支持，可以进入 shared corpus review；用户明确 approve 后才可晋升到用户长期库。
- `work-only`：本作成立，但不应泛化，只进入 work record。
- `pending`：证据不足，进入 `pending.md`。
- `false-positive`：风险扫描或 QC 命中过但确认是误报，应写明为什么误报，必要时收窄规则。

不要把以下内容直接写成全局规则：

- 模型 QC 的单条猜测。
- DLsite 简介推断出的剧情细节。
- 无台本、未抽听、上下文不足的成人术语判断。
- 单个角色或单部作品独有的称呼习惯。
- 风险扫描命中但未确认的候选词。

## 工作记录要求

每个作品都必须在 `$PROJECT_ROOT/learning/work_record.md` 写一条工作记录。建议包含：

- 日期和作品 ID。
- 有无台本。
- 输出范围：本篇、EX、DLC、促销/试听、特典等。
- ASR、翻译、QC 使用的 backend/model，仅作为项目记录，不作为后续硬性要求。
- 主要 QC 发现。
- 可复用经验。
- 已进入 shared corpus review、已获 approve 并同步到用户长期库、或保持项目级的条目。
- 仍留在 `pending.md` 或 work record 里的问题。

即使没有新增全局规则，也要写“无新增可泛化规则”。这能避免后续 agent 误以为该作品还没做学习回收。

## 用户长期库写入要求

用户长期库只接收经过 review 且明确 approve 的 confirmed 条目。工作记录中的内容即使看起来可复用，也必须先进入 shared corpus review；未获 approve 前不得迁移到 `${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/`。

如需把长期库放到其他共享位置，可设置环境变量 `ASMR_SUBTITLE_LEARNING_DIR`，或在解析路径时使用 `scripts/resolve_learning_paths.py "$PROJECT_ROOT" --user-learning-dir <dir>`。`CODEX_HOME` 只作为旧兼容参数，不再是默认学习库位置。

## Shared Corpus Review 流程

每次完整翻译任务收尾时，agent 应延续原来的自然询问方式：先问用户是否还有要修正的地方，并同时询问是否需要现在整理学习库。work record 可以随交付草拟；如果用户还有修正需求，先完成修正和受影响检查，再进入 shared corpus review。review packet、review 队列和迁移动作都应放在用户选择整理/审核学习库之后，除非用户明确要求提前整理学习库。默认不自动晋升到用户长期库。

默认询问顺序：

1. 还有没有需要修正的字幕、报告、范围或交付格式。
2. 是否现在整理本次学习库；如果整理，本次学习候选由 agent 协助撰写/审核、只加入 review 队列，还是跳过。
3. 如果 review 队列里已有 pending 项，是否顺手处理缓冲区，或继续保留到之后。

用户有三种选择：

- `agent-assisted`：agent 根据最终字幕、QC、风险扫描、可读性报告和人工修正提取候选，生成 review packet，并逐条说明证据等级、适用边界和建议目标文件。用户确认后才写入用户长期库。
- `user-review`：agent 只把本项目候选加入 review 队列，用户之后自行审核和迁移。
- `skip`：本次只保留 `$PROJECT_ROOT/learning/work_record.md`，不进入 shared corpus review。

review packet 默认写入：

```text
$PROJECT_ROOT/learning/shared_corpus_review.md
$PROJECT_ROOT/learning/shared_corpus_review.json
```

长期 review 队列默认写入：

```text
${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/review_queue/index.md
${ASMR_SUBTITLE_LEARNING_DIR:-~/ASMR-Subtitle-Translator/learning}/review_queue/index.json
```

`shared_corpus_review.md` 面向人类阅读；`shared_corpus_review.json` 是可执行审核清单。`review_queue/index.json` 是 agent 查找待审核项目的稳定索引。这样后续 agent 不需要用户手动记住哪个项目还没迁移。

进入 shared corpus review 不等于已经进入 shared corpus。只有用户明确确认 `approve` 的条目，才可以晋升到用户长期库的 `references/style.md`、`references/terms.md`、`references/risk-notes.md`、`references/pending.md` 或 `data/subtitle_risk_patterns.local.json`。

agent 在处理完当前项目的 review 选择后，应检查 review 缓冲区：

```bash
python scripts/manage_shared_corpus_review.py \
  --list-queue \
  --json-out "$PROJECT_ROOT/learning/review_queue_status.json"
```

如果 `review_queue_status.json` 里的 `pending_count` 大于 0，最终说明里要提醒用户还有多少个待审 packet，并询问是否现在处理。处理缓冲区时仍然逐条遵守 approve/reject/pending；没有 approve 的条目不得迁移。

常用命令：

```bash
# 用户选择整理学习库后加入 review 队列
python scripts/manage_shared_corpus_review.py \
  "$PROJECT_ROOT" \
  --choice agent-assisted \
  --evidence "$PROJECT_ROOT/learning/work_record.md" \
  --evidence "$PROJECT_ROOT/qc_report.json"

# 后续 agent 查看待审核队列和 pending 数
python scripts/manage_shared_corpus_review.py \
  --list-queue \
  --json-out "$PROJECT_ROOT/learning/review_queue_status.json"

# 用户或 agent 审核 shared_corpus_review.json，把候选 decision 改为 approve/reject/pending 后，再迁移 approve 项
python scripts/manage_shared_corpus_review.py \
  --apply-approved \
  --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"
```

`shared_corpus_review.json` 中每个 candidate 至少要包含：

```json
{
  "id": "RJxxxx-term-001",
  "target": "terms",
  "title": "术语名",
  "evidence_level": "confirmed",
  "source": "RJxxxx / track / subtitle indexes / report path",
  "proposed_entry": "要追加到目标 markdown 的完整条目",
  "boundaries": "适用边界",
  "pollution_risk": "low",
  "decision": "approve",
  "reviewer": "user"
}
```

风险扫描规则使用 `target=risk-patterns`，并提供 `proposed_json` 对象；普通风格、术语、风险说明和 pending 使用 `proposed_entry` 追加到对应 Markdown。

禁止自动晋升的内容：

- `draft` 模式产物。
- 只有模型 QC 猜测、没有源文或上下文证据的内容。
- 只适用于单个作品或单个角色的人设表达。
- 未抽听、无台本、上下文不足的成人术语判断。
- 可能污染其他作品风格的 persona / 羞耻度 / 称呼规则。

## 风格库写入原则

写入用户长期库 `references/style.md` 的内容应当是跨作品可复用的字幕风格原则，而不是某个角色的私人口癖。

适合写入：

- ASMR 听众阅读速度更慢，默认可读性阈值较保守。
- 不为了降低 CPS 把字幕切得过碎。
- 长段纯拟声可压缩为提示，但不能删掉夹在其中的有效台词。
- 亲密口语要自然，不要把普通台词过度润色成另一种风格。

不适合写入：

- “本作女主必须自称姐姐”这类单作设定。
- 只由一次 QC 建议产生、未被源文支持的风格偏好。

## 术语库写入原则

写入用户长期库 `references/terms.md` 的内容应包含来源、推荐译法、不推荐译法和适用条件。

适合写入：

- 成人术语的稳定区分。
- 角色关系中常见称呼。
- 社团、系列或同题材中反复出现的固定表达。

不适合写入：

- 只有一个作品使用、且依赖特殊设定的称呼。
- 没有日文或上下文证据支持的猜测译法。

## 易错词/风险库写入原则

用户长期库 `references/risk-notes.md` 是给人读的说明，重点写“为什么危险、怎么确认、什么时候可能是误报”。用户长期库 `data/subtitle_risk_patterns.local.json` 是给脚本扫的规则，只写可机械匹配的确认风险。

适合写入 `risk-notes.md`：

- ASR 同音误识别链路。
- 模型常见误译。
- 成人术语容易混淆的上下文。
- 风险扫描误报边界。

适合写入 `subtitle_risk_patterns.local.json`：

- 固定错词。
- 明确可匹配的残留日文。
- 高概率需要复查的同音词候选。

写入风险规则时要避免过宽。过宽规则会让后续报告噪声变大，降低用户信任。

## Pending 的用途

用户长期库 `references/pending.md` 和项目级 `$PROJECT_ROOT/learning/pending.md` 不是垃圾箱，而是“需要下次验证的假设”。条目应写清：

- 来源作品和日期。
- 怀疑点。
- 当前证据为什么不足。
- 下次如何验证。

当后续项目确认或否定 pending 条目时，应把它移动到对应 reference，或记录为误报。

## 用户可以怎样要求学习

用户可以用这些方式指挥 agent：

```text
完成后请总结本作品经验，更新项目经验、术语库和易错词说明。
```

```text
这次只记录项目经验，不要写入全局术语库。
```

```text
把这次确认的 ASR 错词加入风险扫描规则。
```

```text
这些称呼只适用于这个 RJ，不要全局化。
```

```text
把本次 QC 误报写进风险说明，后续不要反复提醒。
```

```text
这条我不确定，先放 pending，不要当成规则。
```

## Agent 操作顺序

每次完成作品时，agent 应按这个顺序处理学习库：

1. 读取最终字幕和报告：`qc_report.json`、`risk_report.json`、`readability_report.json`、必要时追加 QC refinement 报告。
2. 运行或参考 `scripts/update_learning_library.py` 生成 work record 草稿。
3. 写入 `$PROJECT_ROOT/learning/work_record.md`，确保本作品有记录。
4. 收尾时询问用户是否还有要修正的地方，以及是否现在整理学习库；如果还有修正需求，先完成修正和受影响检查。
5. 用户选择整理学习库后，询问选择 `agent-assisted`、`user-review` 或 `skip`；未选择时默认保持项目级，不晋升 shared corpus。
6. 从 confirmed 经验中提炼可复用候选，按用户选择写入 `$PROJECT_ROOT/learning/shared_corpus_review.md` 和 `shared_corpus_review.json`，并加入用户长期库的 `review_queue/index.json`；`skip` 时只记录跳过理由。
7. 只有用户明确 approve 的条目，才用 `scripts/manage_shared_corpus_review.py --apply-approved --packet "$PROJECT_ROOT/learning/shared_corpus_review.json"` 写入用户长期库的 `style.md`、`terms.md`、`risk-notes.md` 或 `subtitle_risk_patterns.local.json`。
8. 把证据不足的内容写入 work record、项目 pending，或在 review packet 中保持 `decision=pending`。
9. 运行 `scripts/manage_shared_corpus_review.py --list-queue --json-out "$PROJECT_ROOT/learning/review_queue_status.json"` 检查 review 缓冲区；如果还有 pending packet，询问用户是否现在处理。
10. 做一次学习自检，确认没有把未证实内容写成全局规则。
11. 在最终回复中说明本次学习库更新了哪些文件、review 队列状态，以及哪些内容仍待验证。

## 学习自检

agent 在交付前必须给自己做一轮 learning self-check。自检不是额外模型调用，而是基于本轮证据的整理：

- 本作品是否已经写入 `$PROJECT_ROOT/learning/work_record.md`。
- 是否有 confirmed 经验可以进入用户长期库的 `style.md`、`terms.md`、`risk-notes.md` 或 `subtitle_risk_patterns.local.json`。
- 是否有只适用于本作品的 `project-only` 经验，且没有被误写成全局规则。
- 是否有证据不足的 `pending` 条目。
- 是否有 QC 或风险扫描误报需要记录为 `false-positive`。
- 是否有用户明确要求“不要全局化”“只记录本项目”“先放 pending”。
- 如果没有更新用户长期库，最终说明必须写清原因：无新增可泛化规则、仅项目级经验、证据不足、等待 shared corpus review，或用户要求不全局化。

最终回复中的学习摘要建议包含：

```text
学习库更新：
- work record：已记录 RJxxxx，本次范围/模型/QC 发现/项目级经验。
- shared corpus review：agent-assisted / user-review / skip / 未选择；packet 和 queue 路径。
- approved shared updates：style/terms/risk-notes/risk-patterns 新增或无新增，并说明是否经过 approve。
- pending：新增待验证项或无。
- 未全局化内容：列出原因，例如只适用于本作角色设定。
```

## 最小模板

新增条目建议保留来源和适用边界：

```markdown
### 条目名

- 来源：RJxxxx / 轨道名或字幕编号 / 日期
- 证据等级：confirmed / project-only / pending / false-positive
- 日文或 ASR：...
- 当前中文：...
- 推荐处理：...
- 不推荐处理：...
- 说明：为什么这样处理，适用条件是什么
- 已同步：style / terms / risk-notes / risk-patterns / pending / project-only
```
