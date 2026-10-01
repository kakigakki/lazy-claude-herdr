# lazy-claude-herdr

[English](README.md) · [日本語](README.ja.md) · **中文**

从 [herdr](https://herdr.dev) 的任意 space 找到 Claude Code 会话，并**在它开始的地方**恢复。

在 herdr 里把 Claude Code 分散在多个 space（比如每个 git worktree 一个）运行时，`claude --resume` 只显示当前目录的会话。第二天你已经忘了那个任务在哪个 space。lazy-claude-herdr 把所有 space 的会话放进一个列表，按 Enter 就回到原处：

- **运行中的会话** → 跳到它所在的 pane（即使在别的 space）
- **已停止的会话** → 在目录匹配的 space 里分割 pane 并执行 `claude -r`（没有对应 space 就新建一个）

![herdr 弹窗](demo/herdr.gif)

## 功能

- 在 herdr 任何地方按一个键，以 overlay 弹窗打开
- 每一行显示：运行中标记、环境、最后活动、标题、PR、分支。列对齐，按环境上色
- 输入文字模糊筛选，**输入数字跳到该编号的行**
- `ctrl-s` 切换排序（按时间 / 按环境 / 运行中优先），`ctrl-a` / `ctrl-d` 切换全部期间 / 最近 N 天
- 预览：状态、路径、分支、PR、最后一条指令
- `ctrl-o` 打开该行的操作菜单：fork 到新 pane 恢复、打开 PR、复制 review 请求消息、PR 状态和 CI、阅读会话记录、打开 shell pane、复制恢复命令 / 分支 / ID，以及配置里添加的自定义操作
- 直接键：`ctrl-r` 打开 PR · `ctrl-y` 复制 review 请求 · `ctrl-t` fork
- 界面支持英语、日语、中文
- 在 herdr 外也能当普通 CLI 使用

![列表](demo/demo.gif)

## 依赖

- herdr 0.7 及以上，并安装 Claude integration（`herdr integration install claude`）。不装的话只是没有运行中标记
- [fzf](https://github.com/junegunn/fzf)
- Python 3.11 及以上（只用标准库）
- 可选：[`gh`](https://cli.github.com/)（用于 PR 状态和获取 review 请求的标题）
- macOS 或 Linux

## 安装

```sh
herdr plugin install kakigakki/lazy-claude-herdr
```

在 `~/.config/herdr/config.toml` 里绑定快捷键，然后执行 `herdr server reload-config`：

```toml
[[keys.command]]
key = "prefix+f"
type = "plugin_action"
command = "lazy-claude-herdr.open"
```

如果也想当命令用，把入口软链到 PATH：

```sh
root=$(herdr plugin list --json | python3 -c 'import json,sys; print(next(p["plugin_root"] for p in json.load(sys.stdin)["result"]["plugins"] if p["plugin_id"] == "lazy-claude-herdr"))')
ln -s "$root/bin/lazy-claude-herdr" ~/.local/bin/
```

## 用法

| 在列表里 | |
|---|---|
| 输入文字 | 模糊筛选（标题、环境、分支、`#PR`） |
| 输入数字 | 跳到该编号的行（数字不会触发筛选，搜 PR 号请输入 `#123`） |
| `Enter` | 恢复 |
| `ctrl-o` | 操作菜单（按字母或数字立即执行） |
| `ctrl-s` | 切换排序 |
| `ctrl-a` / `ctrl-d` | 全部期间 / 最近 N 天 |
| `ctrl-r` / `ctrl-y` / `ctrl-t` | 打开 PR / 复制 review 请求 / fork |
| `esc` | 关闭 |

命令行：

```sh
lazy-claude-herdr [关键词]          # 带预筛选打开列表
lazy-claude-herdr -a                # 全部期间
lazy-claude-herdr -l [关键词]       # 只输出列表
lazy-claude-herdr -s env            # 排序: recent | env | live
lazy-claude-herdr --do resume <id>  # 不打开列表，直接执行一个操作
```

## 配置

`~/.config/lazy-claude-herdr/config.toml`（也支持 `$XDG_CONFIG_HOME/...` 和 `$LAZY_CLAUDE_HERDR_CONFIG`）。所有项都可以省略，示例见 [examples/config.toml](examples/config.toml)。

```toml
language = "zh"                 # en | ja | zh

[defaults]
days = 14                       # 0 = 全部期间
sort = "recent"                 # recent | env | live

[review_request]
template = "麻烦 review 一下：{title}\n{url}"   # {title} {url} {number}

[[envs]]                        # 目录的显示名；声明顺序 =「按环境」排序的顺序
match = "~/code/shop-*"         # 路径或 glob，子目录也会匹配
label = "shop-wt"
color = "cyan"                  # 或 "ansi:38;5;208"

[[actions]]                     # 往菜单里加自己的操作
key = "g"
label = "在这里打开 lazygit"
run = "lazygit"                 # {id} {cwd} {branch} {pr} {pr_url} {pr_repo} {title}
mode = "pane"                   # background（默认）| pane | pager
requires = []                   # 其中任一变量为空时不显示
when = "test -d .git"           # 退出码为 0 时才显示（在会话目录里执行）
direct = "ctrl-g"               # 列表里的直接键（可选）
close = false                   # true: background 操作执行后也关闭列表
```

变量展开时会做 shell quote，同时以 `LCH_ID`、`LCH_CWD`、`LCH_BRANCH` … 的形式导出为环境变量。命令在会话目录里用 `/bin/sh` 执行（`pane` 模式则在新 pane 里由你的 shell 执行）。

## 原理

- 会话从 Claude Code 保存在 `~/.claude/projects` 下的记录文件读取（支持 `$CLAUDE_CONFIG_DIR`），并用按文件大小和 mtime 失效的小缓存加速。非交互（`claude -p`）会话和目录已不存在的会话不会显示。
- 通过 CLI 操作 herdr：用 Claude integration 上报的 `agent_session` 判断哪个 pane 在跑哪个会话；space 按 worktree 路径 → pane 目录 → 标签的顺序匹配。
- herdr 关闭 overlay 时会恢复之前的焦点，所以弹窗里的焦点切换交给一个独立进程，等 overlay 关闭后再执行。

## 注意事项

- **Claude Code 的会话记录格式不是公开 API。** 标题、PR 链接等字段可能随 Claude Code 版本变化。字段缺失时会降级（比如 PR 列为空）而不会报错，但请做好偶尔失效的准备。
- 依赖 herdr 0.7 的 API（插件 overlay pane、`agent_session`），在 herdr 0.7.3 上测试过。
- Claude Code 会删除超过 `cleanupPeriodDays`（默认 30 天）的会话，所以「全部期间」大约就是这个范围。

## 开发

```sh
python3 -m unittest discover -s tests   # 只用标准库；herdr、gh、剪贴板用 PATH 上的 fake
vhs demo/demo.tape                      # 重新生成 demo/demo.gif（fixture 数据）
vhs demo/herdr.tape                     # 重新生成 demo/herdr.gif（隔离的 herdr 会话）
herdr session stop lch-demo && herdr session delete lch-demo
```

## 许可证

MIT
