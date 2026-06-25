## 交流语言

始终使用中文与用户交流。代码、commit message、PR 描述等技术输出也用中文。

## 写作要求

所有面向人读的文本——注释、CONTEXT.md、ADR、issue 评论、PR 描述、agent brief、triage notes、Sphinx 文档、Agent 回复——遵守以下原则：

- **善于总结材料**：材料弄全弄准，去粗取精、去伪存真、由此及彼、由表及里，反映事物本质；不堆砌细节、不拼凑清单。
- **不用夸大的修饰词**：不写"权威""强大""完整""单一事实来源"之类的修饰，它们减损力量。
- **注意词语的逻辑界限**：相邻概念要划清，不混用、不模糊。
- **废话应当尽量除去**。
- **通俗、亲切，由小讲到大，由近讲到远，引人入胜**：先讲读者已知／当前的事物，再推到陌生／抽象的；忌一上来就宏大叙事或先搬死人、外国人。
- **与读者完全平等**：靠分析说服，不要装腔作势来吓人；老老实实办事。

## Agent skills

### Issue tracker

以 GitHub issue 管理 Issues 与 PRD，使用 `gh` CLI；外部 PR 不作为 triage 来源。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五状态标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

Single-context 布局：仓库根目录一个 `CONTEXT.md`，架构决策记录在 `docs/adr/`。详见 `docs/agents/domain.md`。
