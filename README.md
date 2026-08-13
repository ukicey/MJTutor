<p align="center">
  <img src="plugins/mjtutor/assets/logo.svg" alt="MJTutor" width="120">
</p>

<h1 align="center">MJTutor</h1>

<p align="center">
  <strong>简体中文</strong> |
  <a href="README.en.md">English</a> |
  <a href="README.ja.md">日本語</a>
</p>

MJTutor 是一个面向 Codex 的本地日麻复盘插件，支持雀魂四人半庄。它结合
Mortal 的动作评估、牌谱中的公开信息和可纠正的长期画像，把一次性的牌谱分析
变成可以持续追问的教学对话。

MJTutor 会区分牌谱事实、Mortal 输出、规则推导和教练推测，也不会把所有与
Mortal 不同的选择直接判定为错误。

[查看更新日志](CHANGELOG.md)

## 功能

- 在 Codex 对话中直接复盘雀魂四人半庄牌谱。
- 使用 Mortal Web 远程分析，无需在本机运行 Mortal 模型。
- 可选择并保存默认 Mortal 分析模型，之后复盘会自动沿用。
- 结合候选动作、Q 值、向听数、分数、牌河、副露和可见牌解释关键决策。
- 将明确反馈和多场牌谱中的重复倾向整理为可确认、纠正或遗忘的长期画像。
- 从牌谱屋同步公开牌局，并在交互目录中筛选和选择要复盘的对局。

## 安装

需要：

- macOS 或 Linux。
- [Codex 桌面端](https://developers.openai.com/codex/app) 或 Codex CLI。
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)。

### Codex 桌面端

在 **Plugins -> Add from GitHub** 中添加：

```text
ukicey/MJTutor
```

安装列表中的 **MJTutor**，然后新建一个任务以加载插件。

### Codex CLI

```bash
codex plugin marketplace add ukicey/MJTutor --ref main
codex plugin add mjtutor@mjtutor
```

安装后新建一个 Codex 任务。可以先发送：

```text
查看我的 MJTutor 配置和已有画像。
```

## 复盘牌谱

把雀魂牌谱链接直接发给 Codex，例如：

```text
用 MJTutor 复盘这份雀魂四麻半庄牌谱，先挑最值得讲的三个决策：
https://game.maj-soul.com/1/?paipu=...
```

第一次复盘时，如果尚未设置默认分析模型，MJTutor 会介绍当前可用模型并协助
选择。默认值会保存在本地，之后仍可随时修改；单局也可以临时改用其他模型。

MJTutor 会打开已经填好牌谱地址的 Mortal Web 页面，并按你的偏好选择模型。如果
Cloudflare Turnstile 自动通过，MJTutor 会直接提交并等待报告；如果页面要求人工
验证，则需要你亲自完成验证。报告生成后，MJTutor 会导入分析结果并开始复盘。
插件不会绕过或代为完成验证。

## 牌局目录

绑定雀魂账号后，可以直接对 Codex 说：

```text
打开我的 MJTutor 牌局目录。
```

目录支持按账号、顺位、日期和复盘状态筛选牌局，也可以手动刷新并选择一局进入
复盘。账号绑定是可选的，不影响直接使用雀魂牌谱链接。

MJTutor 使用经过你确认的雀魂账号 ID 识别账号；在牌谱屋数据中，这个字段名为
`account_id`，并不是另一套牌谱屋账号。昵称只用于显示。牌谱屋的数据可能延迟、
不完整或要求额外验证；遇到访问限制时，MJTutor 会继续显示已经保存的本地记录。

## 长期记忆

复盘、反馈和长期画像默认保存在：

```text
~/.local/share/mjtutor/coach.sqlite3
```

如果设置了 `XDG_DATA_HOME`，保存位置为
`$XDG_DATA_HOME/mjtutor/coach.sqlite3`。也可以用 `MJTUTOR_DATA_DIR` 指定其他目录。

画像中的信息分为三类：

1. **客观观察**：实际动作、Mortal 推荐和当时的局面证据。
2. **暂定画像**：根据多场牌谱提出、仍需验证的倾向。
3. **确认画像**：由你明确确认或纠正的风格、目标、弱点、优势和教学偏好。

数据库独立于插件安装目录，更新或重装插件不会覆盖它。

## 更新

各版本的变化见 [更新日志](CHANGELOG.md)。使用 CLI 更新：

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

更新后请新建一个任务，以加载新版插件。桌面端显示更新按钮时，也可以
直接在插件页面完成更新。

## 反馈

遇到问题、有功能建议，或者希望反馈教学解释与画像效果时，请使用
[GitHub Issues](https://github.com/ukicey/MJTutor/issues/new/choose)。仓库提供问题报告、
功能建议和教学反馈三种模板。

Issue 是公开的。请勿上传 `coach.sqlite3`、访问密钥，或任何不愿公开的真实牌谱和
个人信息；错误日志和截图也请先脱敏。

## 数据与隐私

本地数据库可能包含雀魂账号和昵称、Mortal 报告、牌谱复盘、教学记录和画像证据。
这些数据不会进入 GitHub 仓库或插件包，MJTutor 也不会主动上传数据库或画像。

只有在你选择 Mortal Web 分析时，相应的雀魂牌谱链接才会发送给该第三方服务。
牌谱屋同步同样依赖第三方公开数据服务。

## 许可证

[MIT](LICENSE)
