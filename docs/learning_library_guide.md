# 学习库维护说明

这份文档说明 ASMR Subtitle Translator 的“学习功能”如何使用和维护。这里的学习不是训练模型，而是把每个项目中确认过的经验沉淀到可读、可复查、可被脚本扫描的资料库里，让后续翻译和 QC 更稳定。

## 学习库是什么

学习库由几类文件组成：

- `references/project-lessons.md`：项目经验记录。每完成一个作品都要写一条，哪怕没有新增可泛化规则。
- `references/style.md`：已确认可复用的风格规则，例如口吻、称呼习惯、拟声压缩、ASMR 慢阅读和字幕节奏。
- `references/terms.md`：术语库，例如角色称呼、固定表达、成人术语、社团或系列常用译法。
- `references/risk-notes.md`：面向人读的易错词/风险说明，包括 ASR 同音错、模型常见误译、误报边界和上下文判断方法。
- `data/subtitle_risk_patterns.json`：面向脚本扫描的风险规则，只放可机械匹配的确认风险。
- `references/pending.md`：待验证内容。证据不足、不确定、只听感怀疑或只出现一次的经验先进这里。

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

如果本轮只是只读扫描或中途暂停，可以只写 `pending.md` 或项目 notes；不要把未完成判断写成全局规则。

## 写入分流

先问这个经验属于哪一类：

| 经验类型 | 写入位置 | 例子 |
| --- | --- | --- |
| 只对本作品成立 | `references/project-lessons.md` | 本作姐姐角色固定称呼男主为“你这孩子” |
| 可复用风格 | `references/style.md` | 长段亲吻声可压缩为可读提示，不逐音节刷屏 |
| 稳定术语 | `references/terms.md` | `オナサポ` 译为“自慰辅助/自慰陪伴”，不混同 `フェラ` |
| 人读易错说明 | `references/risk-notes.md` | `そうろう` 易被 ASR 识别成 `僧侶/騒動` |
| 脚本可扫风险 | `data/subtitle_risk_patterns.json` | 正则或固定词命中 `僧侶` 时提示检查是否为 `早漏` |
| 证据不足 | `references/pending.md` | 无台本且未抽听，只怀疑某词是 ASR 幻觉 |

同一个发现可以写入多个地方。例如一个确认的 ASR 错词，解释写进 `risk-notes.md`，机械扫描词写进 `subtitle_risk_patterns.json`，项目发生记录写进 `project-lessons.md`。

## 证据等级

写入前按证据强度分类：

- `confirmed`：台本、日文 ASR、相邻上下文、用户反馈或抽听能支持，可以进入共享 reference。
- `project-only`：本作成立，但不应泛化，可以进入 `project-lessons.md`。
- `pending`：证据不足，进入 `pending.md`。
- `false-positive`：风险扫描或 QC 命中过但确认是误报，应写明为什么误报，必要时收窄规则。

不要把以下内容直接写成全局规则：

- 模型 QC 的单条猜测。
- DLsite 简介推断出的剧情细节。
- 无台本、未抽听、上下文不足的成人术语判断。
- 单个角色或单部作品独有的称呼习惯。
- 风险扫描命中但未确认的候选词。

## 项目经验记录要求

每个作品都必须在 `references/project-lessons.md` 写一条项目记录。建议包含：

- 日期和作品 ID。
- 有无台本。
- 输出范围：本篇、EX、DLC、促销/试听、特典等。
- ASR、翻译、QC 使用的 backend/model，仅作为项目记录，不作为后续硬性要求。
- 主要 QC 发现。
- 可复用经验。
- 已同步到 `style.md` / `terms.md` / `risk-notes.md` / `subtitle_risk_patterns.json` 的条目。
- 仍留在 `pending.md` 的问题。

即使没有新增全局规则，也要写“无新增可泛化规则”。这能避免后续 agent 误以为该项目还没做学习回收。

## 风格库写入原则

写入 `references/style.md` 的内容应当是跨作品可复用的字幕风格原则，而不是某个角色的私人口癖。

适合写入：

- ASMR 听众阅读速度更慢，默认可读性阈值较保守。
- 不为了降低 CPS 把字幕切得过碎。
- 长段纯拟声可压缩为提示，但不能删掉夹在其中的有效台词。
- 亲密口语要自然，不要把普通台词过度润色成另一种风格。

不适合写入：

- “本作女主必须自称姐姐”这类单作设定。
- 只由一次 QC 建议产生、未被源文支持的风格偏好。

## 术语库写入原则

写入 `references/terms.md` 的内容应包含来源、推荐译法、不推荐译法和适用条件。

适合写入：

- 成人术语的稳定区分。
- 角色关系中常见称呼。
- 社团、系列或同题材中反复出现的固定表达。

不适合写入：

- 只有一个作品使用、且依赖特殊设定的称呼。
- 没有日文或上下文证据支持的猜测译法。

## 易错词/风险库写入原则

`references/risk-notes.md` 是给人读的说明，重点写“为什么危险、怎么确认、什么时候可能是误报”。`data/subtitle_risk_patterns.json` 是给脚本扫的规则，只写可机械匹配的确认风险。

适合写入 `risk-notes.md`：

- ASR 同音误识别链路。
- 模型常见误译。
- 成人术语容易混淆的上下文。
- 风险扫描误报边界。

适合写入 `subtitle_risk_patterns.json`：

- 固定错词。
- 明确可匹配的残留日文。
- 高概率需要复查的同音词候选。

写入风险规则时要避免过宽。过宽规则会让后续报告噪声变大，降低用户信任。

## Pending 的用途

`references/pending.md` 不是垃圾箱，而是“需要下次验证的假设”。条目应写清：

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

每次完成作品前，agent 应按这个顺序处理学习库：

1. 读取最终字幕和报告：`qc_report.json`、`risk_report.json`、`readability_report.json`、必要时追加 QC refinement 报告。
2. 运行或参考 `scripts/update_learning_library.py` 生成项目经验草稿。
3. 写入 `references/project-lessons.md`，确保本作品有记录。
4. 从 confirmed 经验中提炼可复用内容，分别写入 `style.md`、`terms.md`、`risk-notes.md`。
5. 只有当风险可机械扫描且足够明确时，更新 `data/subtitle_risk_patterns.json`。
6. 把证据不足的内容写入 `pending.md`。
7. 做一次学习自检，确认没有把未证实内容写成全局规则。
8. 在最终回复中说明本次学习库更新了哪些文件，以及哪些内容仍待验证。

## 学习自检

agent 在交付前必须给自己做一轮 learning self-check。自检不是额外模型调用，而是基于本轮证据的整理：

- 本作品是否已经写入 `references/project-lessons.md`。
- 是否有 confirmed 经验可以进入 `style.md`、`terms.md`、`risk-notes.md` 或 `subtitle_risk_patterns.json`。
- 是否有只适用于本作品的 `project-only` 经验，且没有被误写成全局规则。
- 是否有证据不足的 `pending` 条目。
- 是否有 QC 或风险扫描误报需要记录为 `false-positive`。
- 是否有用户明确要求“不要全局化”“只记录本项目”“先放 pending”。
- 如果没有更新共享 reference，最终说明必须写清原因：无新增可泛化规则、仅项目级经验、证据不足，或用户要求不全局化。

最终回复中的学习摘要建议包含：

```text
学习库更新：
- project-lessons：已记录 RJxxxx，本次范围/模型/QC 发现/项目级经验。
- style/terms/risk-notes：新增或无新增，并说明原因。
- risk patterns：新增或无新增，并说明是否有机械扫描价值。
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
