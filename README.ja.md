# MJTutor

<p align="center">
  <a href="README.md">简体中文</a> |
  <a href="README.en.md">English</a> |
  <strong>日本語</strong>
</p>

MJTutor は、Codex 向けのローカル麻雀牌譜レビュー・プラグインです。
Mortal が牌譜中の行動を評価し、プラグインが MCP 経由で構造化された
根拠を保存します。Codex Skill は、牌譜上の事実、Mortal の評価、ルールに
基づく推論、コーチとしての仮説を、質問や訂正ができる対話形式のレッスンに
まとめます。

> 現在の状態：個人向け MVP。雀魂の四人南風戦、牌譜屋のローカル対局一覧、
> Mortal Web レポートの取り込み、打牌判断の参照、ローカル記憶、訂正可能な
> プレイヤー像に対応しています。Mortal Web の Turnstile は、引き続き
> ユーザー本人が完了する必要があります。

[更新履歴を見る](CHANGELOG.md)

## 機能

- Codex の会話に雀魂の四人南風戦の牌譜 URL を直接入力できます。
- Mortal Web を利用してリモート推論を行い、Mortal の重みをローカルにダウンロード・実行する必要がありません。
- 候補行動、Q 値、確率、シャンテン数、Mortal のモデルバージョンを保存します。
- `mjai_log` を再生し、各判断直前の点数、ドラ表示牌、河、副露、立直状態、見えている牌の枚数を復元します。
- レビュー、明示的なフィードバック、確認・訂正・否定・忘却が可能な長期プレイヤー像をローカル SQLite に保存します。
- 牌譜屋から公開されている四人南風戦の段位戦メタデータを差分同期し、対話型一覧で絞り込み、ページ移動、対局選択ができます。
- ローカルの単一ユーザー向けです。1 つのインストールに複数の雀魂アカウントを紐付けられますが、ログイン機構やマルチユーザー機構はありません。

MJTutor は Mortal との相違を自動的にミスとは判定しません。また、Mortal が
内部の判断理由を自ら説明できるとは主張しません。

## プラグインのインストール

必要なもの：

- macOS または Linux。
- [Codex デスクトップ版](https://developers.openai.com/codex/app)または Codex CLI。
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)。MCP サーバーの初回起動時に Python 3.11+ と軽量な依存関係を準備します。

### Codex デスクトップ版から追加

**Plugins -> Add from GitHub** で、次を入力します。

```text
ukicey/MJTutor
```

一覧から **MJTutor** をインストールしてください。インストール後は新しいタスクを
作成し、Codex にプラグインの Skill と MCP サーバーを読み込ませます。通常の
利用ではリポジトリのクローンや、MJTutor をプロジェクトとして開く必要はありません。

### CLI から追加

```bash
codex plugin marketplace add ukicey/MJTutor --ref main
codex plugin add mjtutor@mjtutor
```

インストール後、新しい Codex タスクを作成してください。最初に次のように
依頼できます。

```text
指導を始めずに、MJTutor の設定と既存のプレイヤー像を確認してください。
```

## 1 半荘をレビューする

雀魂の牌譜 URL を Codex に直接送ります。例：

```text
MJTutor でこの雀魂の四人南風戦をレビューし、まず学習価値の高い3つの判断を選んでください：
https://game.maj-soul.com/1/?paipu=...
```

標準の Mortal Web フローは次のとおりです。

1. プラグインが牌譜 URL、`4.1b` モデル、選択した表示言語を入力済みの Mortal Web ページを生成します。
2. ユーザー本人が表示中のブラウザで Cloudflare Turnstile を完了し、送信します。
3. プラグインが生成された `/report/*.json` レポートを取り込みます。
4. コーチが最初に学習価値の高い判断を最大 3 件選び、質問に応じて詳しく説明します。

MJTutor は Turnstile を回避、解読、外部委託しません。Mortal Web にはこの
プロジェクトが依存できる公開送信 API がないため、この手順を無人で実行する
ことはできません。

## 対局一覧

牌譜屋アカウントを紐付けた後、Codex に次のように依頼できます。

```text
MJTutor の対局一覧を開いてください。
```

一覧は MCP App として描画されるため、大量の対局データを会話コンテキストに
入れる必要がありません。アカウント、順位、日付、レビュー済みかどうかで
絞り込み、対局を選択して既存の Mortal Web フローへ進めます。MCP App を
表示できないクライアントでも、`list_koromo_games`、`sync_koromo_games`、
`prepare_selected_game_review` は個別に利用できます。

自動同期は軽量な機会駆動方式です。前回の試行から 30 分以上経過している場合
のみ、一覧を開いたときに差分取得を行います。手動更新も可能です。MJTutor は
常駐プロセスをインストールせず、Codex の終了中にバックグラウンド動作せず、
同期した対局を Mortal に自動送信しません。

初回同期では、既定で過去 1 年分を取得します。以降は牌譜屋への反映遅延を
考慮し、過去 1 週間を重ねて取得します。対局は UUID で重複排除され、
`~/.local/share/mjtutor/coach.sqlite3` に保存されます。

牌譜屋ではブラウザ認証やサイト管理者発行のアクセスキーが必要になる場合が
あります。MJTutor は認証を回避せず、ローカルキャッシュを表示し続けながら
`verification_required` を報告します。サイト管理者からアクセスキーが提供
された場合は、MCP 起動環境に `MJTUTOR_KOROMO_TOKEN` を設定できます。
牌譜屋のウェブサイトを通常どおり閲覧する操作は MJTutor の管理外です。

## 長期記憶とプレイヤー像

プラグインの記憶は、チャット履歴やプラグインのインストール先とは独立して
います。既定の保存先は次のとおりです。

```text
~/.local/share/mjtutor/coach.sqlite3
```

`XDG_DATA_HOME` が設定されている場合は
`$XDG_DATA_HOME/mjtutor/coach.sqlite3` に保存されます。`MJTUTOR_DATA_DIR` で
保存先ディレクトリを指定することもできます。

データベースでは根拠を 3 段階に分けます。

1. **客観的な観察：** 実際の行動、Mortal の推奨、候補順位、Q 値の差、局面情報、モデルバージョン。これらを自動的に弱点とは判定しません。
2. **暫定的なプレイヤー像：** 複数対局で繰り返された行動について、適用範囲と確信度を付けた仮説。支持例と反例の両方を保存します。
3. **確定したプレイヤー像：** ユーザーが明示的に確認または訂正した打ち方、弱点、長所、目標、疑問、理解済みの内容、指導上の好み。

データベースはプラグイン外にあるため、GitHub marketplace の更新、プラグインの
更新、再インストールによってプレイヤー像が上書きされることはありません。

### 旧プロジェクト方式からの移行

旧版のデータベースはリポジトリ内の `data/coach.sqlite3` にあります。MJTutor を
利用中の古いタスクを終了してから、バックアップして移行してください。

```bash
mkdir -p "$HOME/.local/share/mjtutor"
cp data/coach.sqlite3 "$HOME/.local/share/mjtutor/coach.sqlite3"
```

移行先にすでにデータベースがある場合は、直接上書きしないでください。両方を
バックアップしてから、残すデータを判断してください。

## プラグインの更新

バージョンごとの変更点と移行上の注意は[更新履歴](CHANGELOG.md)を参照してください。

GitHub で新しいバージョンが公開された後、CLI では次の手順で確実に更新できます。

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

その後、新しいタスクを作成して更新後の Skill と MCP サーバーを読み込ませます。
デスクトップ版のプラグイン画面に更新ボタンが表示される場合も、同等の処理です。

更新は `~/.local/share/mjtutor/` を変更しません。プラグインのマニフェストは
セマンティック・バージョニングを使用し、リリース時には関連するバージョン番号を
揃えて更新します。Codex は、実行中の既存タスクに新版プラグインをホットスワップ
しません。

## アカウントの紐付け

アカウントの紐付けは任意です。紐付けなくても牌譜の取り込み、客観的観察の蓄積、
長期プレイヤー像の利用ができます。

MJTutor は表示用にニックネームを使い、ユーザーが確認した牌譜屋の `account_id` を
安定した識別子として使います。ニックネームは重複・変更される可能性があり、
プラグインは同名の検索結果や牌譜 URL だけで本人と断定しません。

牌譜屋は主に金の間、玉の間、王座の間の段位戦を収録しています。データには遅延や
欠落があり得ます。牌譜屋に存在しないことは、雀魂アカウントに `account_id` が
ないことを意味しません。

## データとプライバシー

ローカルデータベースには、次の情報が含まれる場合があります。

- 雀魂アカウント、現在のニックネーム、ニックネーム履歴。
- Mortal の元レポート JSON。
- レビューと、各判断直前の公開卓上情報。
- 客観的な判断記録、指導メモ、プレイヤー像の根拠。

これらのデータは GitHub リポジトリやプラグインパッケージには含まれません。
MJTutor はデータベースやプレイヤー像を自動アップロードしません。ユーザーが
Mortal Web での解析を明示的に選んだ場合に限り、対象の雀魂牌譜 URL が第三者の
サイトへ渡されます。

## 現在の制限

- 雀魂の四人南風戦のみ対応します。牌譜形式だけでは、段位戦と友人戦を常に確実に区別できるとは限りません。
- Mortal Web では人による認証が必要です。
- 牌譜屋のデータには遅延や欠落があり、ブラウザ認証が必要な場合もあります。未収録であることは対局が存在しなかった証拠にはなりません。
- 対局一覧は対応ホストが表示する MCP App であり、独立したデスクトップアプリではありません。
- 雀魂への自動ログイン、常駐バックグラウンド処理、対局中のリアルタイム支援、リモートホスティングは提供しません。
- 現在のプラグインランチャーは macOS/Linux 向けです。
- Mortal と `mjai-reviewer` は外部プロジェクトであり、本リポジトリにはソースコードやモデルの重みを含みません。

## 開発

実行用ソースコードは `plugins/mjtutor/` のみに置かれています。リポジトリ直下の
Python プロジェクトはプラグインのテストとビルド用であり、Codex に
「プロジェクト方式」で MJTutor を自動読込させるものではありません。

```bash
git clone https://github.com/ukicey/MJTutor.git
cd MJTutor
uv sync
uv run ruff format --check plugins/mjtutor/src tests
uv run ruff check plugins/mjtutor/src tests
uv run pytest
uv run python -m compileall -q plugins/mjtutor/src tests
```

Python コードは Ruff で整形・静的検査し、行長を 88 文字に統一します。変更を
提出する前に `uv run ruff format plugins/mjtutor/src tests` を実行すると、自動で
整形できます。

プラグイン構成：

```text
.agents/plugins/marketplace.json
plugins/mjtutor/.codex-plugin/plugin.json
plugins/mjtutor/.mcp.json
plugins/mjtutor/assets/game-catalog.html
plugins/mjtutor/bin/mjtutor-mcp
plugins/mjtutor/skills/coach-mahjong-soul/
plugins/mjtutor/src/mjtutor/
```

Mortal は AGPL-3.0-or-later、`mjai-reviewer` は Apache-2.0 でライセンスされて
います。MJTutor はウェブまたはプロセスのインターフェースを通してのみ利用します。

## ライセンス

[MIT](LICENSE)
