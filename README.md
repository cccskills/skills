# cccskills/skills

[cccskills](https://cccskills.com)（日本語で探せる Agent Skills マーケット）が作っている Agent Skills です。Claude Code・Codex CLI など、Agent Skills に対応したエージェントで使えます。

| スキル | できること |
| --- | --- |
| [skill-md-review](skills/skill-md-review/SKILL.md) | SKILL.md を cccskills の客観評価と同じ 4 項目（指示の明確さ・手順の具体性・安全面・導入のしやすさ）で A/B/C 採点し、直し方を出す |
| [cccskills-find](skills/cccskills-find/SKILL.md) | やりたい作業に合うスキルを cccskills の公開 API で探し、実行スコア・安全面・ライセンスで比べて、入れるコマンドまで案内する |
| [jp-business-mail](skills/jp-business-mail/SKILL.md) | 日本語のビジネスメールを、場面と相手に合わせて書く・直す。敬語の誤りを直した理由も示す |

## 入れ方

```bash
npx skills add https://github.com/cccskills/skills --skill skill-md-review
npx skills add https://github.com/cccskills/skills --skill cccskills-find
npx skills add https://github.com/cccskills/skills --skill jp-business-mail
```

手で入れるなら、`skills/<name>/` のフォルダを `~/.claude/skills/`（Claude Code）にコピーします。

## 安全面

- `skill-md-review` と `jp-business-mail` は、外部への送信もコマンドの実行もしません。
- `cccskills-find` は、検索キーワードとスキルの slug だけを `cccskills.com` の公開 API に送ります。スキルを入れるコマンドは、ユーザーが了承してから実行します。

## リンク

- スキルを探す: https://cccskills.com
- 評価の基準: https://cccskills.com/evaluation
- API・MCP: https://cccskills.com/developers

## ライセンス

MIT
