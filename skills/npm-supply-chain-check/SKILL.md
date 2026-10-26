---
name: npm-supply-chain-check
description: JavaScript / TypeScript のプロジェクトを、npm のサプライチェーン攻撃（乗っ取られたパッケージの悪性バージョン、インストール時に動くスクリプト、CI からの認証情報の窃取）への備えという観点で読むだけで点検し、直すべき設定を優先順に示す。ロックファイルの全パッケージについて公開からの日数とインストールスクリプトを npm レジストリで調べる。「npm の依存は大丈夫？」「サプライチェーン攻撃の対策をしたい」「axios みたいな乗っ取りに備えたい」ときに使う。Audits a JS project's npm supply-chain posture (release-age gates, install scripts, lockfiles, CI tokens).
---

# npm-supply-chain-check

npm では、人気パッケージの開発者アカウントが乗っ取られ、悪性のバージョンが公開される事件が続いています（2025 年の自己増殖型ワーム Shai-Hulud、2026 年の axios の侵害など）。悪性バージョンの多くは、数時間から数日で見つかって取り下げられます。そのため、次の 3 つで被害の大半を防げます。

- **公開されたばかりのバージョンを入れない**
- **インストール時のスクリプトを勝手に動かさない**
- **CI の認証情報を絞る**

このスキルは、プロジェクトがこの 3 つをできているかを点検します。

## 守ること

- 点検は **読むだけ**。`npm install` などのインストール、パッケージのスクリプトの実行、設定ファイルの書き換えはしない。直すかどうかはユーザーが決める。
- 外部への通信は、付属のスクリプトが `https://registry.npmjs.org` からパッケージの公開情報（公開日時・スクリプト定義）を取得するだけ。プロジェクトのファイルや認証情報は送らない。
- `.npmrc` などにトークンが書かれていても、値は表示しない。「書かれている」ことだけを伝える。

## 前提

- Node.js 18 以上（付属スクリプトが組み込みの `fetch` を使う）。
- ネットワークに出られない環境では手順 3 を飛ばし、その旨を結果に書く。

## 手順

### 1. パッケージマネージャーとバージョンを確かめる

- ロックファイルから判断する: `package-lock.json`（npm）・`pnpm-lock.yaml`（pnpm）・`yarn.lock`（Yarn）・`bun.lock`（Bun）。`package.json` の `packageManager` も見る。
- バージョンを確かめる（`npm -v`・`pnpm -v`・`yarn -v`）。手順 2 の設定が使えるかどうかがバージョンで変わる。
- ロックファイルがリポジトリに **コミットされていない**（`.gitignore` に入っている、存在しない）なら、それを最初の指摘にする。

### 2. 設定を点検する

| # | 点検すること | 見る場所 | 望ましい状態 |
| --- | --- | --- | --- |
| 1 | 公開から日の浅いバージョンを避ける設定 | npm 11.10 以上: `.npmrc` の `min-release-age`（日数）／pnpm: `pnpm-workspace.yaml` の `minimumReleaseAge`（分。pnpm 11 は既定で 1440）／Yarn 4.10 以上: `.yarnrc.yml` の `npmMinimalAgeGate` | 1〜7 日の待ち時間がある。除外（`minimumReleaseAgeExclude` など）は最小限 |
| 2 | インストールスクリプトの扱い | npm: `.npmrc` の `ignore-scripts`／pnpm: `onlyBuiltDependencies`・`strictDepBuilds`（pnpm 10 以降は既定で依存のスクリプトを動かさない）／Yarn: `enableScripts` | 依存のスクリプトは既定で止め、必要なものだけ許可している |
| 3 | CI のインストール方法 | `.github/workflows/*.yml` など | `npm ci`・`pnpm install --frozen-lockfile`・`yarn install --immutable` で、ロックファイルどおりに入れている |
| 4 | GitHub Actions の固定 | `uses:` の行 | 外部の Action はタグではなくコミット SHA で固定。`pull_request_target` で外部 PR のコードを checkout していない |
| 5 | CI の権限とトークン | ワークフローの `permissions:`・`secrets.*` | `permissions` を最小に絞っている。npm の公開には長期トークンではなく Trusted Publishing（OIDC）を使っている |
| 6 | 直接の依存の書き方 | `package.json` | `*`・`latest`・Git の URL・知らないレジストリを使っていない |
| 7 | 認証情報の置き方 | `.npmrc`・`.env` がコミットされていないか | トークンをリポジトリに置いていない |

### 3. ロックファイルの全パッケージを調べる

```bash
node <このスキルのフォルダ>/scripts/lockfile-check.mjs <プロジェクトのフォルダ> --days 7
```

- `--days`: これより新しいバージョンを「公開されたばかり」として挙げる（既定 7）。
- `--max`: 調べる件数の上限（既定 5000）。大きいプロジェクトで時間がかかるときに使う。
- 結果（JSON）の読み方:
  - `recent`: 公開から `--days` 日未満のバージョン。**最優先で確かめる。** そのパッケージの GitHub のリリースや変更履歴にそのバージョンがあるか、npm のページで公開者がいつもと同じかを見る。乗っ取りの事件が報じられていれば、そのバージョンと照らし合わせる。
  - `installScripts`: インストール時にスクリプト（preinstall / install / postinstall）が動くパッケージ。手順 2 の #2 で許可しているものと照らし合わせ、知らないものがあれば挙げる。
  - `missing`: レジストリにもう無いバージョン（取り下げ済み）。悪性で取り下げられた可能性があるので、必ず挙げる。
  - `deprecated`: 非推奨。セキュリティ上の理由が書かれていれば挙げる。
  - `errors`: 取得に失敗したもの。社内レジストリのパッケージなどは対象外として扱う。

### 4. 結果を返す

```markdown
## npm-supply-chain-check: <プロジェクト>

パッケージマネージャー: pnpm 10.18 ／ ロックファイル: あり（コミット済み） ／ 調べた依存: 612 件

### すぐ直す
1. **公開日数の待ちがない** — `pnpm-workspace.yaml` に次を足す（pnpm 10.16 以上）
   ```yaml
   minimumReleaseAge: 1440
   ```
2. ...

### 確かめる
| パッケージ | バージョン | 理由 |
| --- | --- | --- |
| foo | 3.2.1 | 公開から 0.5 日。GitHub のリリースに 3.2.1 がない |

### できていること
- CI は `pnpm install --frozen-lockfile`
```

- 「すぐ直す」は効果の大きい順に並べ、それぞれに貼れる設定の差分を付ける。設定名と単位（日・分）は、手順 1 で確かめたバージョンのものを使う。分からなければ公式ドキュメントで確かめるよう添える。
- 待ち時間の設定は、公開から日の浅い悪性バージョンには効くが、長く潜伏する攻撃は防げない。過信しないよう一言添える。
- 直すかどうかを聞き、ユーザーが了承したときだけ設定ファイルを編集する。

## このスキルについて

- 作者: cccskills（https://github.com/cccskills/skills）
- 外部への通信は `registry.npmjs.org` からの公開情報の取得だけ。インストール・スクリプトの実行はしない。
