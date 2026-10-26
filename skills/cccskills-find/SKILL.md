---
name: cccskills-find
description: やりたい作業に合う Agent Skills を cccskills.com の公開 API で探し、実行検証のスコア・安全面の判定・ライセンス・更新日で比べて、入れるコマンドまで案内する。「〇〇できるスキルある？」「議事録用のスキルを探して」「いいスキルを見つけて入れたい」ときに使う。Finds and compares Agent Skills for a task via the cccskills.com API (execution score, safety checks, license) and shows the install command.
---

# cccskills-find

ユーザーがやりたい作業を聞き、cccskills（https://cccskills.com）の公開 API で候補のスキルを探し、比べて、入れ方まで案内する。

## 前提

- `curl` が使えること。`jq` があれば使うが、なくてもよい（JSON をそのまま読む）。
- API キーは不要。キーなしだと **1 IP あたり 1 日 50 回・1 分 10 回** まで検索できる。回数を増やしたいときは、環境変数 `CCCSKILLS_API_KEY` にキー（`ccs_live_...`。https://cccskills.com/developers で発行）を入れておけば、それを使う。
- 外部への送信: 検索キーワードとスキルの slug を `cccskills.com` に送る。それ以外（ファイルの中身・会話の内容・環境変数）は送らない。キーワードに社名や個人名などの機密が入りそうなときは、一般的な言葉に言い換えてから送る。

## 手順

### 1. 依頼を検索語にする

ユーザーの依頼から、検索語を 1〜3 個作る。

- 日本語と英語の両方を用意する（例: 「議事録」と `meeting minutes`）。cccskills は日本語の全文検索に対応しているが、英語で書かれたスキルも多い。
- 作業の名前（「議事録」「コードレビュー」「請求書」）を使い、「便利」「AI」のような広すぎる語は避ける。
- 依頼があいまいなら、検索の前に 1 問だけ確かめる（例: 「議事録は、録音の文字起こしから作りますか、メモから作りますか？」）。

### 2. 検索する

```bash
AUTH=()
[ -n "$CCCSKILLS_API_KEY" ] && AUTH=(-H "Authorization: Bearer $CCCSKILLS_API_KEY")
curl -sG "${AUTH[@]}" "https://cccskills.com/api/v1/skills/search" \
  --data-urlencode "q=議事録" \
  --data-urlencode "limit=10" \
  --data-urlencode "sortBy=relevance" \
  --data-urlencode "lang=ja"
```

- まず関連順（`sortBy=relevance`）で引く。続けて `sortBy=score&minScore=1` で同じ語を引くと、実行検証を済ませたスキルだけが返る。検証済みのスキルはまだ一部なので、こちらは空になることが多い。空なら関連順の結果だけで進める。
- 主なパラメータ: `q`（必須）・`limit`（〜50）・`sortBy`（relevance / score / stars / recent）・`minScore`（0〜100）・`category`・`price`（free / paid）・`official`（`true` で公式の発行元に限る）・`lang`（ja / en / zh / ko）。
- 応答は `{ "success": true, "data": { "skills": [...] } }`。失敗すると `{ "success": false, "error": { "code", "message" } }`。`RATE_LIMITED` が返ったら、上限に達したことと、上のキーの設定方法を伝えて止める。

### 3. 候補を絞る

検索結果から、依頼に合うものを 3〜5 件選ぶ。次に当てはまるものは外すか、後ろに回す。

- `isCopy: true`（別のスキルのコピー）。代わりに `copyOf` が指す代表のスキルを候補にする。
- `isFork: true` で、元のリポジトリが候補に入っているもの。
- `description` を読んで、依頼と作業が違うもの。

### 4. 詳細を取って比べる

選んだ候補ごとに詳細を取る（検索回数は使わない）。

```bash
curl -s "${AUTH[@]}" "https://cccskills.com/api/v1/skills/<slug>?lang=ja"
```

次の表にまとめる。

| 見るもの | フィールド | 読み方 |
| --- | --- | --- |
| 実行スコア | `executionScore` | スキルあり・なしで Claude Code に同じ依頼をさせて比べた点数（0〜100）。何も変わらないスキルが 55 点前後。`null` は未検証 |
| 安全面 | `checks.safety.grade` / `reason` | SKILL.md の中身から判定した A/B/C。外部送信・削除・認証情報の扱い |
| 導入のしやすさ | `checks.setup.grade` / `reason` | 必要なツールや API キーが書かれているか |
| 使いどころ | `useCases` | 依頼に合っているかの確認 |
| ライセンス | `license` | 業務で使うなら確認する。`null` はライセンスの記載なし |
| 更新日 | `updatedAt` | 長く更新がないものは注意 |
| 価格 | `priceJpy` | 0 は無料 |
| スター数 | `stars` | 実行スコアがないときの参考。品質の保証ではない |

### 5. 結果を返す

```markdown
## 「議事録」に使えるスキル

| | スキル | 実行スコア | 安全面 | 導入 | ライセンス | 一言 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [board-minutes](https://cccskills.com/skills/...) | 72 | A | A | Apache-2.0 | 取締役会の議事録を社内書式で作る |
| 2 | ... | 未検証 | B | A | MIT | ... |

**おすすめ: 1**。理由: 実行スコアが高く、外部送信がない。
```

- おすすめは 1 つに絞り、理由を 1〜2 文で書く。依頼との合い方を前提に、実行スコアがあればそれを最も重く見る。55 点を下回るスキルは、入れないほうが結果が良かったことを意味するので、おすすめにしない。実行スコアがない候補どうしは、安全面 → 導入のしやすさ → 更新日 → スター数（`stars`）の順で比べる。
- 安全面が C のものは、表に残すが、おすすめにしない。理由（`checks.safety.reason`）を添える。
- 合う候補がないときは、正直にそう伝え、検索語を変えて再検索するか、`skill-md-review` などで自作することを提案する。

### 6. 入れ方を示す

GitHub のスキル（`source: "github"`）は、`githubUrl`（`https://github.com/<owner>/<repo>/tree/...`）から `<owner>/<repo>` を取り出し、次のコマンドを示す。

```bash
npx skills add https://github.com/<owner>/<repo> --skill <name>
```

- **コマンドはユーザーが了承してから実行する。** 実行前に、入るスキルの SKILL.md を GitHub で読んでおくよう勧める（`githubUrl` を示す）。
- cccskills で直接配布されているスキル（`source: "native"`）や有料のスキル（`priceJpy > 0`）は、`url`（cccskills のスキルページ）から入手するよう案内する。

## このスキルについて

- 作者: cccskills（https://github.com/cccskills/skills）
- API の仕様: https://cccskills.com/developers
- 評価の基準: https://cccskills.com/evaluation
- MCP サーバー（`https://cccskills.com/mcp`）を使っている環境なら、`search_skills`・`get_skill` ツールで同じことができる。
