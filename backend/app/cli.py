"""Explicit administrative commands; no sample insertion during application startup."""

import argparse
import json
import sys

from app.clock import SystemClock
from app.config import get_settings
from app.db import create_db_engine
from app.services.seed import SeedError, reset_demo, seed_database, seed_preview


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="店舗受取アプリ 管理コマンド")
    commands = parser.add_subparsers(dest="command", required=True)
    seed_parser = commands.add_parser("seed", help="少量サンプルを投入")
    seed_parser.add_argument("--dry-run", action="store_true", help="DBに接続せず投入予定を表示")
    seed_parser.add_argument("--confirm-database", help="承認後に対象DB名を明示")
    reset_parser = commands.add_parser("reset-demo", help="既存データを削除してサンプルを入れ直す")
    reset_parser.add_argument("--confirm-database", required=True)
    jobs_parser = commands.add_parser("jobs", help="定期処理")
    jobs_sub = jobs_parser.add_subparsers(dest="operation", required=True)
    jobs_run = jobs_sub.add_parser("run")
    jobs_run.add_argument("codes", nargs="*", choices=[f"J-{n:02}" for n in range(1, 8)])
    orders_parser = commands.add_parser("orders", help="注文管理")
    orders_sub = orders_parser.add_subparsers(dest="operation", required=True)
    for operation in ("show", "resume", "cancel"):
        command_parser = orders_sub.add_parser(operation)
        command_parser.add_argument("order_number")
        if operation == "cancel":
            command_parser.add_argument("--reason", required=True)
    payments_parser = commands.add_parser("payments", help="決済照合")
    payments_sub = payments_parser.add_subparsers(dest="operation", required=True)
    payments_reconcile = payments_sub.add_parser("reconcile")
    payments_reconcile.add_argument("order_number")
    mails_parser = commands.add_parser("mails", help="メール管理")
    mails_sub = mails_parser.add_subparsers(dest="operation", required=True)
    mails_list = mails_sub.add_parser("list")
    mails_list.add_argument("--status", choices=["PENDING", "FAILED", "SENT", "SIMULATED"])
    mails_resend = mails_sub.add_parser("resend")
    mails_resend.add_argument("notification_id")
    args = parser.parse_args(argv)
    clock = SystemClock()
    if args.command == "seed" and args.dry_run:
        print(json.dumps(seed_preview(clock), ensure_ascii=False, indent=2))
        return 0
    try:
        settings = get_settings()
        if args.command not in {"seed", "reset-demo"}:
            from app.main import create_app
            from app.services.administration import command

            app = create_app(settings, clock)
            try:
                print(json.dumps(command(app, args), ensure_ascii=False, indent=2))
                return 0
            finally:
                app.state.engine.dispose()
        database = settings.connection_url().database
        if not args.confirm_database or args.confirm_database != database:
            raise SeedError("承認後に--confirm-databaseで接続先のDB名を指定してください。")
        password = settings.seed_password.get_secret_value() if settings.seed_password else ""
        if len(password) < 12:
            raise SeedError("SEED_PASSWORDに12文字以上の非公開パスワードを指定してください。")
        if password == settings.connection_url().password:
            raise SeedError("デモ用パスワードはDB接続用とは別の値にしてください。")
        engine = create_db_engine(settings)
        try:
            if args.command == "reset-demo":
                result = reset_demo(engine, clock, password, settings.app_env)
            else:
                result = seed_database(engine, clock, password)
        finally:
            engine.dispose()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        # Deliberately hide DB errors and config values, including SQL parameters.
        print("処理に失敗しました。接続設定とDBの状態を確認してください。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
