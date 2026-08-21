<p align="center">
  <img src="plugins/mjtutor/assets/logo.svg" alt="MJTutor" width="120">
</p>

<h1 align="center">MJTutor</h1>

<p align="center">
  <a href="README.md">简体中文</a> |
  <strong>English</strong> |
  <a href="README.ja.md">日本語</a>
</p>

MJTutor is a local riichi-mahjong coaching plugin for Codex with support for
four-player Mahjong Soul hanchan. It combines Mortal's action evaluations,
public game information, and a correctable long-term profile to turn a
one-off review into a coaching conversation you can continue and question.

MJTutor distinguishes game facts, Mortal outputs, rule-based reasoning, and
coaching hypotheses. It does not automatically treat every disagreement with
Mortal as a mistake.

[View the changelog](CHANGELOG.md)

## Features

- Review four-player Mahjong Soul hanchan directly in a Codex conversation.
- Use Mortal Web for remote analysis without running Mortal models locally.
- Choose and save a default Mortal model for future reviews.
- Calculate shanten, effective draws, unseen-copy counts, and tenpai
  continuations with a deterministic hand-shape engine, separately from
  Mortal candidates and Q values.
- Explain key decisions using scores, rivers, melds, and visible tiles.
- Turn explicit feedback and recurring patterns across games into a long-term
  profile that can be confirmed, corrected, or forgotten.
- Browse and filter local reviews in the game catalog. With a personal Koromo
  API key, you can also sync public games and select one for review.

## Installation

Requirements:

- macOS or Linux.
- [Codex desktop](https://developers.openai.com/codex/app) or Codex CLI.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/).

### Codex desktop

In **Plugins -> Add from GitHub**, enter:

```text
ukicey/MJTutor
```

Install **MJTutor** from the list, then start a new task to load the plugin.

### Codex CLI

```bash
codex plugin marketplace add ukicey/MJTutor --ref main
codex plugin add mjtutor@mjtutor
```

Start a new Codex task after installation. A useful first prompt is:

```text
Show my MJTutor setup and existing profile.
```

## Review a game

Send a Mahjong Soul game-log URL directly to Codex, for example:

```text
Use MJTutor to review this four-player Mahjong Soul hanchan. Start with the three decisions that have the highest teaching value:
https://game.maj-soul.com/1/?paipu=...
```

On the first review, MJTutor briefly introduces the available models and helps
you choose when no default has been saved. You can change the default later or
use another model for a single game.

MJTutor opens Mortal Web with the game URL filled in and selects your preferred
model. If Cloudflare Turnstile completes automatically, MJTutor submits the
form and waits for the report. If the page requires interaction, complete the
verification yourself. MJTutor then imports the report and starts the review;
it never bypasses or completes verification for you.

## Game catalog

Ask Codex:

```text
Open my MJTutor game catalog.
```

The game catalog is primarily a browser for reviews already imported and saved
locally. It can filter by account, placement, date, and review status, and lets
you reopen a game for viewing or review. Using the local catalog does not require
account binding and does not affect direct review from a Mahjong Soul URL.

To additionally sync public games from Koromo, you can bind a Mahjong Soul
account. MJTutor identifies it with the UID shown in the Mahjong Soul profile
and its nickname. The first Koromo link also needs one paipu URL that you confirm
belongs to that account. MJTutor derives Koromo's separate internal account ID
from the URL, so you do not need to find or remember it. Koromo data may be
delayed or incomplete.

Synchronization requires a personal API key issued by the site owner and
configured locally as `MJTUTOR_KOROMO_TOKEN`. MJTutor does not run a cloud
service and never embeds, shares, or forwards the developer's key, so each user
of the public plugin must request their own key. Never paste the key into a chat
or issue, or commit it to GitHub. Without a configured key, the catalog stays
local and does not send synchronization requests to Koromo.

## Long-term memory

Reviews, feedback, and the long-term profile are stored by default at:

```text
~/.local/share/mjtutor/coach.sqlite3
```

When `XDG_DATA_HOME` is set, the database is stored at
`$XDG_DATA_HOME/mjtutor/coach.sqlite3`. You can select another directory with
`MJTUTOR_DATA_DIR`.

Profile information is separated into three categories:

1. **Objective observations:** actual actions, Mortal recommendations, and
   evidence from the decision context.
2. **Tentative profile:** patterns suggested across multiple games that still
   need confirmation.
3. **Confirmed profile:** styles, goals, weaknesses, strengths, and teaching
   preferences you explicitly confirm or correct.

During a full-game review, the coach selectively compares current decisions with
earlier games, tests possible style or weakness patterns, and looks for
counterexamples. It mentions a profile insight only when a new cross-game pattern
emerges, an earlier interpretation changes materially, or the insight directly
helps the current explanation, rather than repeating profile conclusions after
every answer.

The database is separate from the plugin installation, so updates and
reinstallation do not overwrite it.

## Updating

See the [changelog](CHANGELOG.md) for version changes. To update with the CLI:

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

Start a new task after updating so it loads the new plugin version. When the
desktop plugin page shows an update button, you can update there instead.

## Feedback

Use [GitHub Issues](https://github.com/ukicey/MJTutor/issues/new/choose) to
report a problem, suggest a feature, or comment on the coaching explanations
and profile quality. The repository provides a template for each type.

Issues are public. Do not upload `coach.sqlite3`, access keys, private game
logs, or other information you do not want to disclose. Sanitize logs and
screenshots before attaching them.

## Data and privacy

The local database may contain Mahjong Soul accounts and nicknames, Mortal
reports, game reviews, coaching notes, and profile evidence. This data is not
included in the GitHub repository or plugin package, and MJTutor does not
upload the database or profile automatically.

A Mahjong Soul game-log URL is sent to Mortal Web only when you choose that
analysis flow. Game synchronization likewise relies on Koromo as a third-party
public data service.

## License

[MIT](LICENSE)
