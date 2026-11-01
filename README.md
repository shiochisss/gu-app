# 店舗受取アプリ

「00_実装ガイド」のステップ1（土台）を実装した段階です。Backendの起動、PostgreSQL接続、稼働確認、共通エラー、ログ、Frontendのビルドと保護設定、自動検査の設定があります。商品・注文の画面とデータは今後作ります。現時点でFrontendの `/` が404になるのは想定どおりです。

## 用意するもの

- Python 3.12
- Node.js 24 LTS
- Docker Desktop（起動しておく）

## 1. データベースを起動する

プロジェクト直下で実行します。

```sh
docker compose up -d --wait
```

PostgreSQL 17に、開発用 `pickup` と自動テスト専用 `pickup_test` が作られます。ポートは自分のPCだけからアクセスできる5432番です。DBデータはDockerのボリュームに残ります。テストDB作成SQLは初回だけ実行されます。既存ボリュームに `pickup_test` がない場合は次を実行してください（既存データは消しません）。

```sh
docker compose exec db psql -U pickup_app -d postgres -c 'CREATE DATABASE pickup_test OWNER pickup_app;'
```

## 2. Backendを設定・起動する

```sh
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

`.env` の `JWT_SECRET`・`QR_SECRET`・`BFF_SHARED_SECRET`・`JOB_SECRET` を、それぞれ別のランダム値に置き換えます。次のコマンドを4回実行すると64文字の値を4つ作れます。

```sh
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

健康確認だけならStripeへ接続しないため、`.env.example` の `sk_test_replace_me`・`whsec_replace_me` で起動できます。決済を作る段階で実際のStripeテスト用キーに差し替えます。`sk_live_` などの本番キーは起動時に拒否されます。`.env` はGitに登録しない設定です。

```sh
alembic upgrade head
uvicorn app.main:app --reload --port 8000 --no-access-log
```

業務テーブルのマイグレーションはステップ2で追加します。現段階の `alembic upgrade head` は接続と管理用テーブルの準備だけを行います。アクセス記録はアプリが秘密値を除いたJSONで出すため、Uvicornの通常アクセスログは無効にしています。

別のターミナルで確認できます。

```sh
curl -i http://localhost:8000/healthz
```

DBに接続できれば200と `{"status":"ok"}` が返ります。`http://localhost:8000/docs` でAPIの説明が見られます。`APP_ENV=azure-test` では `/docs`・`/redoc`・`/openapi.json` は404になります。正式な起動手順は `bash startup.sh`（Alembic実行後にGunicornを起動）です。

## 3. Frontendを設定・起動する

別のターミナルを開き、プロジェクト直下から実行します。

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run gen:api
npm run dev
```

`.env.local` の `BFF_SHARED_SECRET` はBackendと同じ値にします。BFFの処理自体はステップ3で追加します。`npm run gen:api` は起動中のローカルBackendからAPIの型を生成します。`src/types/api.d.ts` は手で編集しません。

ブラウザで `http://localhost:3000` を開けますが、店舗選択画面はステップ4なので現在は404です。APIの説明はBackendの8000番ポートで確認してください。

## 4. 自動検査する

Backendは `backend/` 内で仮想環境を有効にして実行します。専用の `pickup_test` DBを指定してください。開発用DBを誤って指定した場合はテストが拒否します。

```sh
export TEST_DATABASE_URL='postgresql+psycopg://pickup_app:pickup_local@localhost:5432/pickup_test'
ruff check .
pytest -q
pip-audit --disable-pip --no-deps -r requirements.txt
```

`TEST_DATABASE_URL` がない場合、実DBの結合テスト1件はスキップします。全件確認するには必ず指定してください。脆弱性検査のオプションは、依存関係がすべて固定済みのファイルをそのまま調べ、一時仮想環境の再作成を省くためです。

Frontendは `frontend/` 内で実行します。

```sh
npm run lint
npm run typecheck
npm run test
npm audit --audit-level=high
npm run build
```

ビルドはNext.js標準のWebpack方式です。この作業環境ではTurbopack内部のポート作成が制限されたため、繰り返し実行できる方式を指定しています。依存関係の版は設計書の指定範囲に固定しています。

配布用の単体サーバーを確認する場合は次を実行します。

```sh
mkdir -p .next/standalone/.next
cp -R .next/static .next/standalone/.next/
cp -R public .next/standalone/
PORT=3000 HOSTNAME=127.0.0.1 node .next/standalone/server.js
```

## CIと次の工程

`.github/workflows/ci.yml` にGitHub Actionsの検査を用意しています。BackendはPostgreSQL 17付きでテスト・静的解析・脆弱性検査を行い、Frontendはインストール・静的解析・型検査・Jest・脆弱性検査・ビルドを行います。実行対象はpull requestとmainへのpushです。

2026年11月1日、既存の設計書の変更履歴を保ったまま、GUアプリ全体を単一リポジトリへ統合しました。接続先は `https://github.com/shiochisss/gu-app.git` です。Sourcetreeでは「既存のローカルリポジトリを追加」で `GUアプリ` フォルダそのものを選択します。`gu-docs/`・`frontend/`・`backend/` を個別に追加する必要はありません。既存のGitHub上の `gu-docs` は残しています。移行前のバックアップは `.migration-backups/` にあり、Gitには登録されません。

確認の記録と設計書の整合修正は [ステップ1実装結果](gu-docs/06_ステップ1実装結果.md) を参照してください。[初回CI](https://github.com/shiochisss/gu-app/actions/runs/41278392482)はBackend・Frontendとも成功しました。次のステップ2で業務用のテーブルとデモデータを作ります。
