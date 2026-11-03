# 店舗受取アプリ

Step9までのアプリ機能を実装しました。購入者の注文・支払連携・取消・受取QR、店員の準備・欠品・引き渡し・在庫・POS・営業時間、定期ジョブと管理コマンドが動きます。Step10のデプロイ用コードも準備済みですが、Azureのアプリ環境は未構築で、デプロイとStripe設定はユーザー指定により後日行います。手順は [残タスクと再開手順](gu-docs/15_残タスクと再開手順.md) にまとめています。詳細は [Step7〜9実装結果](gu-docs/13_ステップ7〜9実装結果.md) と [デプロイ・受け入れ確認](gu-docs/14_デプロイ・受け入れ確認.md) を参照してください。

## 今回のAzure MySQLへPCから接続する場合

Azure MySQL 8.4の自分用DB `gu_app_shiochi` を利用します。`backend/.env` は作成済みで、接続先・DB名が設定されています。ユーザー名とパスワードはPC内のこのファイルにだけ入力します。`.env` と `frontend/.env.local` はGit対象外です。

```dotenv
DATABASE_HOST=gen12-mysql-pos.mysql.database.azure.com
DATABASE_PORT=3306
DATABASE_NAME=gu_app_shiochi
DATABASE_USER='提供されたユーザー名'
DATABASE_PASSWORD='提供されたパスワード'
DATABASE_SSL=true
```

個別設定を使う場合は `DATABASE_URL` を同時に設定しないでください（URLが優先されます）。`@` や `:` を含むパスワードもURLエンコードなしで扱います。シングルクォート自体を含む場合はdotenvのルールに合わせてダブルクォート等で囲みます。

起動は2つのターミナルで行います。

```sh
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

```sh
cd frontend
npm run dev -- --hostname 127.0.0.1
```

確認先は `http://localhost:8000/docs` と `http://localhost:8000/healthz`。DB接続できればhealthzが200と `{"status":"ok"}` を返します。ステップ2のテーブル定義と少量シードは実装済みで、Azureにもユーザー同意後に作成・投入済みです。投入予定は `python -m app.cli seed --dry-run` でDBに接続せず確認できます。Frontendは `http://localhost:3000` で店舗選択画面を表示します。

接続がタイムアウトする場合、AzureのMySQLサーバーの「設定→ネットワーク」で現在のクライアントIPが許可されているか確認します。TLSは証明書・ホスト名まで検証します。共有Azureのアプリ用DBを自動テストで初期化しません。

以下はDockerで自分のPCに別の開発用・テスト用MySQLを用意する手順です。Azure接続だけを試す場合はDocker不要です。

## 用意するもの

- Python 3.12
- Node.js 24 LTS
- Docker Desktop（起動しておく）

## 1. データベースを起動する

プロジェクト直下で実行します。

```sh
docker compose up -d --wait
```

MySQL 8.4に、開発用 `pickup` と自動テスト専用 `pickup_test` が作られます。ポートは自分のPCだけからアクセスできる3306番です。DBデータはDockerのボリュームに残ります。テストDB作成SQLは初回だけ実行されます。既存ボリュームに `pickup_test` がない場合は次を実行してください（既存データは消しません）。

```sh
docker compose exec db mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS pickup_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin; GRANT ALL PRIVILEGES ON pickup_test.* TO 'pickup_app'@'%';"
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

`alembic upgrade head` は25個のアプリ用テーブルとAlembic管理用テーブルを作成します。ここで示した通常コマンドはローカルDB用です。Azureへの実行は承認後に対象DB名を明示した `alembic -x confirm_database=gu_app_shiochi upgrade head` を使います。シードは自動投入されません。アクセス記録はアプリが秘密値を除いたJSONで出すため、Uvicornの通常アクセスログは無効にしています。

別のターミナルで確認できます。

```sh
curl -i http://localhost:8000/healthz
```

DBに接続できれば200と `{"status":"ok"}` が返ります。`http://localhost:8000/docs` でAPIの説明が見られます。`APP_ENV=azure-test` では `/docs`・`/redoc`・`/openapi.json` は404になります。正式なサーバー起動手順は `bash startup.sh`（Gunicornのみ）です。マイグレーションとシードは別の管理操作として承認後に行います。

## 3. Frontendを設定・起動する

別のターミナルを開き、プロジェクト直下から実行します。

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run gen:api
npm run dev
```

`.env.local` の `BFF_SHARED_SECRET` はBackendと同じ値にします。BFF（ブラウザとBackendの間をつなぐ処理）は実装済みです。`npm run gen:api` は起動中のローカルBackendからAPIの型を生成します。`src/types/api.d.ts` は手で編集しません。

ブラウザで `http://localhost:3000` を開き、店舗を選ぶと商品一覧へ進めます。色・サイズを選んでカートへ追加できます。注文手続きは `/checkout` へ進みます。未ログインならログイン後に戻ります。ローカルでは `BACKEND_BASE_URL=http://127.0.0.1:8000`、`FRONTEND_BASE_URL=http://localhost:3000` を指定します。127.0.0.1で画面を開いた場合はlocalhostへ揃え、Cookieとログインを安定させます。APIの説明はBackendの8000番ポートで確認してください。

会員登録は `/register`、一般ログインは `/login`、店員ログインは `/staff/login` です。既存サンプルの `buyer1@example.com`、`staff.shinjuku@example.com` 等で試す場合、パスワードは `backend/.env` の `SEED_PASSWORD` の値です。DB接続パスワードとは別です。新規会員登録・ログインは接続中のDBへユーザー・認証情報を書き込むため、架空のテスト用情報を使ってください。

店員ログイン後は `/staff/orders` の注文一覧へ進みます。POSは `/staff/pos`。売上履歴は `/staff/pos/sales`、在庫管理は `/staff/inventory`。POSは支払区分を記録する簡易機能で、このステップではカード決済サービスへ接続しません。売上確定・取消・入荷・棚卸・破損登録は接続中のDBの在庫を実際に更新します。ブラウザ検証・自動テストはAzureではなく、独立したローカルの `pickup_test` だけで行いました。

## 注文・テスト決済・メールを確認する

購入者でログインし、商品→カート→「注文手続きへ」から進みます。確認画面で受取条件に同意すると支払手続きへ進めます。見積もりは10分で更新され、注文時にも金額・在庫・予定をBackendで照合します。カードの入力内容はStripeのPayment Elementが扱い、アプリへはConfirmationTokenのIDだけを渡します。

現在のStripe設定は仮の値です。実Stripeの試験前に、同じテストアカウントのキーをローカルのGit対象外ファイルへ設定してください。

- `backend/.env`：`STRIPE_SECRET_KEY`（`sk_test_...`）、`STRIPE_WEBHOOK_SECRET`（`whsec_...`）。
- `frontend/.env.local`：`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`（`pk_test_...`）。変更後はFrontendを再起動／再ビルドします。
- Stripe側のテスト用決済手段はカードだけにします。Webhook送信先はBackendの `/api/v1/payments/webhook`。BFF経由では受け付けません。

仮の公開キーでは支払画面に設定案内を出します。通常起動ではStripe用処理を使い、架空の決済を成功扱いにする切替は設けていません。`FakePaymentGateway` は自動テストと独立したローカル確認用プロセスにだけ注入しました。実Stripeの成功／拒否／3Dセキュア確認は [Stripe公式のテスト手順](https://docs.stripe.com/testing) に従って行います。

注文一覧は `/orders`。`MAIL_MODE=simulate` では外部へメールを送らず、`DEV_TOOLS_ENABLED=true` と `NEXT_PUBLIC_DEV_TOOLS_ENABLED=true` の場合に `/dev/mailbox` で確認できます。購入者には本人宛て、店員には担当店舗の注文メールだけを返します。

準備開始・欠品・準備完了（決済確定）、受取QR・引き渡し・遅延時の取消、未解決決済・仮確保の回収は実装済みです。注文受付時には利用枠だけを確保し、店員の準備完了時に売上を確定します。定期処理のAPIは `/internal/jobs/run` でJOB_SECRETを必要とし、GitHub Actionsの定期実行は公開先とSecretsの設定後に有効化します。

## 4. 自動検査する

Backendは `backend/` 内で仮想環境を有効にして実行します。専用の `pickup_test` DBを指定してください。開発用DBを誤って指定した場合はテストが拒否します。

```sh
export TEST_DATABASE_URL='mysql+pymysql://pickup_app:pickup_local@127.0.0.1:3306/pickup_test?charset=utf8mb4'
ruff check .
pytest -q
pip-audit --disable-pip --no-deps -r requirements.txt
```

`TEST_DATABASE_URL` がない場合、実DBを使う結合テストはスキップします。全件確認するには必ず指定してください。脆弱性検査のオプションは、依存関係がすべて固定済みのファイルをそのまま調べ、一時仮想環境の再作成を省くためです。

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

`.github/workflows/ci.yml` にGitHub Actionsの検査を用意しています。BackendはMySQL 8.4付きでテスト・静的解析・脆弱性検査を行い、Frontendはインストール・静的解析・型検査・Jest・脆弱性検査・ビルドを行います。実行対象はpull requestとmainへのpushです。

2026年11月1日、既存の設計書の変更履歴を保ったまま、GUアプリ全体を単一リポジトリへ統合しました。接続先は `https://github.com/shiochisss/gu-app.git` です。Sourcetreeでは「既存のローカルリポジトリを追加」で `GUアプリ` フォルダそのものを選択します。`gu-docs/`・`frontend/`・`backend/` を個別に追加する必要はありません。既存のGitHub上の `gu-docs` は残しています。移行前のバックアップは `.migration-backups/` にあり、Gitには登録されません。

確認の記録と設計書の整合修正は [ステップ1実装結果](gu-docs/06_ステップ1実装結果.md) を参照してください。[初回CI](https://github.com/shiochisss/gu-app/actions/runs/41278392482)はBackend・Frontendとも成功しました。ステップ2のコード・ローカル試験と、承認済みのAzureへの作成・投入は完了しています。GitHubへのpushは別途承認待ちです。ステップ3〜9をローカル検証済みです。2026年11月4日にユーザーからStep2〜9のcommit・pushの許可を得ました。Azure構築・デプロイ・Stripe設定は後日実施し、自動デプロイと定期ジョブは無効のままにします。詳細は [ステップ2実装結果](gu-docs/09_ステップ2実装結果.md) と [ステップ3・4実装結果](gu-docs/10_ステップ3・4実装結果.md) を参照してください。

## 定期処理と管理

Backend内から `python -m app.cli jobs run` でJ-01〜05を、`python -m app.cli jobs run J-06 J-07` で日次処理を実行できます。接続中のDBを更新する管理操作です。今回の検証はローカル専用DBだけで実施しました。

`orders show/resume/cancel`、`payments reconcile`、`mails list/resend` も実装済みです。操作前に `python -m app.cli --help` と該当サブコマンドの `--help` で引数を確認してください。

配布ZIPは `backend/.venv/bin/python scripts/package_release.py all`、Azureへの変更なしで計画を表示するには `backend/.venv/bin/python scripts/deploy_azure.py --create --configure-github --configure-only` を使います。詳細と未実施項目は [デプロイ・受け入れ確認](gu-docs/14_デプロイ・受け入れ確認.md) に記録しています。

## 作業の承認ルール

公開GitHubへのpushと、Azureへのサンプル投入は、内容と検証結果を説明したうえでユーザーの明示的な同意を得てから実行します。reset-demoによる削除・入れ直しも個別に確認します。詳細は [サンプル投入計画と承認ルール](gu-docs/08_サンプル投入計画と承認ルール.md) を参照してください。

## 少量サンプルの準備と実行

予定は2店舗・利用者4人・商品6件・SKU24種類・店舗別在庫48件・初期在庫履歴41件・担当店舗2件・採番2件、合計129行です。

```sh
cd backend
source .venv/bin/activate
python -m app.cli seed --dry-run
```

Azureへの実行は、実行対象・件数・テスト結果の確認と同意を得た後だけ行います。`SEED_PASSWORD` は `backend/.env` に非公開で設定済みで、DB接続パスワードとは別の値です。DBにはユーザーごとにArgon2idでハッシュ化して保存します。

- テーブル作成：`alembic -x confirm_database=gu_app_shiochi upgrade head`
- 初回投入：`python -m app.cli seed --confirm-database gu_app_shiochi`
- 再投入時は全サンプルが存在すれば何も上書きしません。一部だけ存在する場合は中止して確認します。
- `reset-demo --confirm-database gu_app_shiochi` は全アプリデータを消して入れ直す別操作です。個別の同意が必要で、productionでは拒否します。

専用DBを指定した検証は `pytest -q --mysql-url='mysql+pymysql://pickup_app:pickup_local@127.0.0.1:3306/pickup_test?charset=utf8mb4'` で実行できます。試験開始時に専用DB内の既知のアプリテーブルを作り直します。名前と接続先を検証し、Azureのアプリ用DBは拒否します。
