# Issue tracker: GitHub

本仓库的 issue 与 PRD 以 GitHub issue 形式存在，所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`。多行正文使用 heredoc。
- **查看 issue**：`gh issue view <number> --comments`，可用 `jq` 过滤评论，同时读取标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，可附加 `--label` 与 `--state` 过滤。
- **评论 issue**：`gh issue comment <number> --body "..."`
- **添加 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <number> --comment "..."`

仓库由 `git remote -v` 自动推断 —— 在仓库克隆内运行 `gh` 时会自动识别。

## 将 PR 作为 triage 来源

**PR 作为请求来源：否。**（若本仓库将外部 PR 视为功能请求，则设为 `yes`；`/triage` 会读取此标志。）

设为 `yes` 时，PR 与 issue 使用相同标签和状态流转，对应 `gh pr` 命令：

- **查看 PR**：`gh pr view <number> --comments`，并用 `gh pr diff <number>` 查看差异。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，仅保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的项（排除 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论 / 打标签 / 关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 与 PR 共享同一编号空间，因此裸 `#42` 可能是两者之一 —— 先用 `gh pr view 42`，失败再回退到 `gh issue view 42`。

## 当 skill 说“发布到 issue tracker”

创建一个 GitHub issue。

## 当 skill 说“获取相关工单”

运行 `gh issue view <number> --comments`。
