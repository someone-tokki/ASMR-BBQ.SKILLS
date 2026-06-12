# ASMR 日译中语料库索引

用途：为 ASMR 日译中字幕提供可持续更新的风格、术语、风险和项目经验入口。详细内容拆在 `references/`，按任务需要读取，避免每次加载全部历史。

当前版本：2026-06-12  
首次来源作品：`RJ01201653`，有初稿台本，含本篇、EX、促销/试听音频。

## 读取顺序

- 开工分流：先读 `docs/task_routing.md`。
- 翻译或手修前：读 `references/style.md` 和 `references/terms.md`。
- 风险扫描、QC 修正或处理 `qc_report.json` 前：读 `references/risk-notes.md`，必要时再读 `references/terms.md`。这里的风险说明主要是易错词、ASR 误识别、常见误译和误报边界。
- 查看过往作品经验：读 `references/project-lessons.md`。
- 不确定条目和后续验证：读 `references/pending.md`。
- 机械扫描规则：使用 `data/subtitle_risk_patterns.json`，由 `tools/scan_subtitle_risks.py` 默认读取。

## 使用规则

- 翻译时把 reference 作为参考，不要机械套用；不同作品的人设、关系、时代、方言会改变译法。
- 本项目记录的模型和工具只代表当次经验，不是后续项目的硬性要求。
- 校对后把新经验追加到对应 reference；不确定内容写入 `references/pending.md`，不要写成定论。
- 每条新增内容尽量包含来源作品、轨道、上下文和日期。
- 风险扫描只是候选，必须结合日文 ASR、台本、相邻字幕、作品标题和人工/agent 证据确认。

## 作品后学习循环

每完成一个作品，agent 必须从本次产物中提炼可复用经验，而不是只交付字幕。主要来源包括最终 `.zh.srt` / `.zh.vtt`、`qc_report.json`、`risk_report.json`、`readability_report.json`、人工修正记录、台本复核记录和抽听记录。

写入原则：

- 每个完成的作品都必须在 `references/project-lessons.md` 留下一条项目记录，哪怕结论是“没有新增可泛化规则”。
- 从每个项目中继续提炼可复用规则：能帮助后续翻译更自然的内容，写入 `references/style.md`；稳定术语写入 `references/terms.md`；确认过的 ASR 错词、同音误识别、模型常见误译和误报边界写入 `references/risk-notes.md`。
- 可机械扫描的确认风险额外写入 `data/subtitle_risk_patterns.json`，但解释、来源和适用条件仍放在 `references/risk-notes.md`。
- `risk_report.json` 的真阳性要沉淀，误报要记录为什么误报，并在必要时收窄扫描规则。
- 无台本、未抽听或证据不足的经验必须写入 `references/pending.md` 并标明 `待验证`。
- 不把只适用于单个角色、单个作品设定的表达写成通用规则；可以写入 `references/project-lessons.md` 作为“本作适用”。

## 新增条目格式

建议使用以下格式：

```markdown
### 术语或问题名

- 来源：RJxxxx / 轨道名或编号 / 有无台本 / 日期
- 日文或 ASR：...
- 推荐译法：...
- 不推荐译法：...
- 说明：为什么这样译，适用条件是什么
- 标签：术语 / ASR错词 / 语气 / 拟声 / 人称 / 成人场景 / 待验证
```
