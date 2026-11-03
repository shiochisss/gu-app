# MySQL接続設定と変更記録

本書は接続移行時点の記録。後続の専用MySQLでの50件の試験と少量シードの実装結果は [ステップ2実装結果](09_ステップ2実装結果.md) を参照。

2026年11月1日。課題で提供されたAzure Database for MySQL Flexible Serverを利用するというユーザーの方針に合わせ、土台をMySQL 8.4へ変更した。

## 接続先

- ホスト：gen12-mysql-pos.mysql.database.azure.com
- DB：gu_app_shiochi（ユーザー作成済み）
- 版：MySQL 8.4（Azure画面でユーザー確認）
- 認証情報：backend/.envにPC上で入力。Git対象外。Frontendへ配信しない。
- TLS：certifiの信頼ストアで証明書・ホスト名を検証。TLS 1.2以上。

## 変更したもの

- 同期DBドライバーをpsycopgからPyMySQLへ変更。SQLAlchemyとAlembicの採用は維持。
- 個別のホスト・DB名・ユーザー名・パスワードからURL.createで接続URLを組み立て、パスワードの特殊文字に対応。
- DB接続をUTF-8（utf8mb4）・UTC・READ COMMITTEDに統一。日時はdatetime(6)とUTCDateTimeでUTCのtz付きPython日時へ往復させる。
- ローカルComposeとCIのサービスDBをMySQL 8.4へ変更。自動テストは専用pickup_testを使用し、共有Azureのgu_app_shiochiは初期化しない。
- 要件・基本・詳細・テスト設計を改訂。UUID型、JSON型、検索照合、番号採番、QR有効行の一意制約、Webhook・冪等処理・ジョブ排他・デモ初期化にあったPostgreSQL専用指定をMySQL向けに置換。
- MySQLには同じ方式のシーケンスがないため、ステップ2の設計にnumber_countersを追加（2行）。QRの有効行の一意性は生成列で維持する。これらの業務テーブルはまだ作成していない。

## 確認結果

- pytest：32件成功、実MySQL専用DBのテスト1件は未実施（ローカルMySQL 8.4／Dockerなし）。
- ruff：成功。
- pip-audit：MySQL対応後の固定依存に既知の脆弱性なし。
- Azureへの初回接続はTCPタイムアウト（2003）。ユーザーが現在のPCのIPをファイアウォールに追加・保存した後、読み取り専用の接続に成功した。
- 実接続：DB=gu_app_shiochi、版=8.4.9-azure、SELECT 1成功、TLS有効、セッションのタイムゾーンは+00:00。証明書・ホスト名の検証は有効のまま。
- 実HTTP：localhost:8000/docs=200、localhost:8000/healthz=200とstatus=ok、localhost:3000/=404（業務画面未実装のため想定どおり）。BackendとFrontendはユーザーが確認できるよう起動したまま。
- 接続確認はSELECT／SHOWのみで、Azure上のテーブル作成・データ更新はしていない。
- GitHubの既存CI成功記録はPostgreSQL時点のもの。MySQL構成のCIはまだ実行していない。

## 調査した公式資料

- [Azure MySQLのTLS](https://learn.microsoft.com/en-us/azure/mysql/flexible-server/security-tls)
- [PyMySQL接続オプション](https://pymysql.readthedocs.io/en/latest/modules/connections.html)
- [MySQL 8.4の分離レベル](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)
- [MySQL 8.4の名前付きロック](https://dev.mysql.com/doc/refman/8.4/en/locking-functions.html)

## 次に確認すること

Azure接続とローカルBackendのhealthzは確認済み。MySQL 8.4専用テストDBでの結合テストと、更新したCIの実行は別途確認が必要。業務テーブルとシードはステップ2で実装する。
