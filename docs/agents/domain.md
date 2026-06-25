# Domain Docs

说明工程类 skill 在探索本仓库代码库时，应如何消费领域文档。

## 探索前阅读

- 仓库根目录的 **`CONTEXT.md`**，或
- 仓库根目录的 **`CONTEXT-MAP.md`**（若存在）—— 它指向每个上下文各自的 `CONTEXT.md`，按需阅读相关上下文。
- **`docs/adr/`** —— 阅读与即将处理区域相关的 ADR。多上下文仓库还需检查 `src/<context>/docs/adr/` 中的上下文级决策。

如果上述文件不存在，**静默继续**。不要提示缺失，也不要主动建议创建。`/domain-modeling` skill（可通过 `/grill-with-docs` 与 `/improve-codebase-architecture` 进入）会在术语或决策真正需要明确时惰性创建它们。

## 文件结构

Single-context 仓库（大多数仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context 仓库（根目录存在 `CONTEXT-MAP.md`）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 全系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文级决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用词汇表中的术语

当输出中命名领域概念（issue 标题、重构提案、假设、测试名等）时，使用 `CONTEXT.md` 中定义的术语，不要滑向词汇表明确避免的同义词。

如果所需概念尚未出现在词汇表中，这是一个信号 —— 要么你在发明项目不使用的语言（请重新考虑），要么确实存在缺口（记下来供 `/domain-modeling` 处理）。

## 标记 ADR 冲突

如果输出与现有 ADR 冲突，请显式指出，而非静默覆盖：

> _与 ADR-0007（event-sourced orders）冲突 —— 但值得重新讨论，因为…_
