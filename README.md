# translate-markdown

将英文 Markdown 文档翻译成中文的工具。基于 Python + DeepSeek API，单文件脚本。

## 功能

- 英文 Markdown 翻译为中文
- 保护代码块、行内代码、图片路径不被翻译
- 表格整体翻译，保留 Markdown 表格语法
- 断点续翻（checkpoint 机制，中断后自动从上次进度继续）
- GUI（PyQt6）和 CLI 双入口

## 安装

需要 Python 3.13+，使用 [uv](https://docs.astral.sh/uv/) 管理依赖。

```bash
git clone <repo-url>
cd translate-markdown
uv sync
```

## 配置

配置文件位于 `~/.config/translate-markdown/config.json`，包含：

```json
{
  "api_key": "your-deepseek-api-key",
  "api_base": "https://api.deepseek.com"
}
```

首次使用前需设置 `api_key`。可以手动创建配置文件，也可以通过 GUI 界面保存。

## 使用方法

### CLI

```bash
# 翻译指定文件，生成 article_zh.md（与源文件同目录）
uv run python main.py article.md
```

### GUI

```bash
uv run python main.py --gui
```

GUI 界面提供：
- 文件选择对话框
- API Key 和请求地址输入（可保存到本地配置）
- 实时进度条和日志输出

## 项目结构

```
main.py              # 单文件脚本（配置、LLM、后端、前端）
tests/               # 测试
CONTEXT.md           # 领域词汇表
docs/adr/            # 架构决策记录
pyproject.toml       # 项目配置
```
