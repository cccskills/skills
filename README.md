# cccskills/skills

[cccskills](https://cccskills.com)（日本語で探せる Agent Skills マーケット）が作っている Agent Skills です。Claude Code・Codex CLI など、Agent Skills に対応したエージェントで使えます。

### セキュリティ

| スキル | できること |
| --- | --- |
| [skill-security-audit](skills/skill-security-audit/SKILL.md) | スキルやエージェント設定（CLAUDE.md・フック・MCP 設定）を、入れる前・開く前に読むだけで検査する。見えない文字の隠し命令・認証情報の持ち出し・リバースシェルなどを見つける |
| [npm-supply-chain-check](skills/npm-supply-chain-check/SKILL.md) | npm のサプライチェーン攻撃への備えを点検する。ロックファイルの全パッケージについて、公開からの日数とインストールスクリプトを調べ、直すべき設定を示す |
| [incident-first-response-jp](skills/incident-first-response-jp/SKILL.md) | 情報漏えい・ランサムウェア被害の初動を整理し、個人情報保護委員会への報告の期限と項目、公表文・本人への通知文の下書きを作る |

### 仕事・スキル作り

| スキル | できること |
| --- | --- |
| [skill-md-review](skills/skill-md-review/SKILL.md) | SKILL.md を cccskills の客観評価と同じ 4 項目（指示の明確さ・手順の具体性・安全面・導入のしやすさ）で A/B/C 採点し、直し方を出す |
| [cccskills-find](skills/cccskills-find/SKILL.md) | やりたい作業に合うスキルを cccskills の公開 API で探し、実行スコア・安全面・ライセンスで比べて、入れるコマンドまで案内する |
| [jp-business-mail](skills/jp-business-mail/SKILL.md) | 日本語のビジネスメールを、場面と相手に合わせて書く・直す。敬語の誤りを直した理由も示す |

### 創作

| スキル | できること |
| --- | --- |
| [charatone](skills/charatone/SKILL.md) | キャラクターの台詞の「声」を設計・点検する。語尾・一人称・呼び方・相づちを人物ごとに決め、「〜だ。」ばかりの台詞（AI が書いた台本に多い）を直す。話者ごとの語尾の偏りを数える点検スクリプト付き |

## 入れ方

```bash
npx skills add https://github.com/cccskills/skills --skill skill-security-audit
npx skills add https://github.com/cccskills/skills --skill npm-supply-chain-check
npx skills add https://github.com/cccskills/skills --skill incident-first-response-jp
npx skills add https://github.com/cccskills/skills --skill skill-md-review
npx skills add https://github.com/cccskills/skills --skill cccskills-find
npx skills add https://github.com/cccskills/skills --skill jp-business-mail
npx skills add https://github.com/cccskills/skills --skill charatone
```

手で入れるなら、`skills/<name>/` のフォルダを `~/.claude/skills/`（Claude Code）にコピーします。

## 安全面

- `skill-md-review`・`jp-business-mail`・`incident-first-response-jp` は、外部への送信もコマンドの実行もしません。
- `skill-security-audit` の検査スクリプトは、標準ライブラリだけで動き、対象を読むだけです（実行・送信をしません）。
- `npm-supply-chain-check` の検査スクリプトは、`registry.npmjs.org` からパッケージの公開情報を取得するだけです。インストールやスクリプトの実行はしません。
- `charatone` の点検スクリプトは、標準ライブラリだけで動き、台本ファイルを読むだけです。
- `cccskills-find` は、検索キーワードとスキルの slug だけを `cccskills.com` の公開 API に送ります。スキルを入れるコマンドは、ユーザーが了承してから実行します。

## リンク

- スキルを探す: https://cccskills.com
- 評価の基準: https://cccskills.com/evaluation
- API・MCP: https://cccskills.com/developers

## ライセンス

MIT
