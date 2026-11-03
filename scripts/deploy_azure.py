"""Explicit Azure-test deployment. Dry-run is the default; never modify the shared DB."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def run(arguments, *, input_text=None, allow_missing=False):
    result = subprocess.run(
        arguments, input=input_text, text=True, capture_output=True, check=False
    )
    if result.returncode:
        if allow_missing and (
            "ResourceNotFound" in result.stderr
            or "ResourceGroupNotFound" in result.stderr
        ):
            return None
        if "AADSTS" in result.stderr or "az login" in result.stderr:
            raise RuntimeError(
                "Azureの再ログインが必要です。az login を実行してください。"
            )
        raise RuntimeError(
            f"{arguments[0]} {arguments[1]} の処理に失敗しました（秘密値は表示しません）。"
        )
    return result.stdout


def settings_file(folder, name, values):
    path = folder / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(values, stream)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="省略時は計画のみ表示")
    parser.add_argument(
        "--configure-only",
        action="store_true",
        help="AzureとGitHubの設定だけ行い、ZIPはCIでデプロイ",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="未作成ならFree F1のテスト用リソースを作成",
    )
    parser.add_argument(
        "--configure-github",
        action="store_true",
        help="発行プロファイルとジョブ設定をGitHubへ保存",
    )
    parser.add_argument("--resource-group", default="rg-pickup-app-shiochi")
    parser.add_argument("--plan", default="plan-pickup-shiochi")
    parser.add_argument("--frontend", default="app-pickup-front-shiochi")
    parser.add_argument("--backend", default="app-pickup-back-shiochi")
    parser.add_argument("--repository", default="shiochisss/gu-app")
    args = parser.parse_args()
    plan = {
        "resourceGroup": args.resource_group,
        "plan": args.plan,
        "sku": "F1",
        "location": "japaneast",
        "frontend": args.frontend,
        "backend": args.backend,
        "createMissing": args.create,
        "configureGithub": args.configure_github,
        "configureOnly": args.configure_only,
        "packages": [".release/backend.zip", ".release/frontend.zip"],
        "databaseChanges": False,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    from app.config import Settings
    from dotenv import dotenv_values

    config = Settings(_env_file=ROOT / "backend/.env")
    if config.connection_url().database != "gu_app_shiochi" or not config.database_ssl:
        raise RuntimeError("Azure向けの接続はTLS付きgu_app_shiochiを指定してください。")
    frontend_config = dotenv_values(ROOT / "frontend/.env.local")
    publishable = frontend_config.get("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY", "") or ""
    for value, prefix in [
        (config.stripe_secret_key.get_secret_value(), "sk_test_"),
        (config.stripe_webhook_secret.get_secret_value(), "whsec_"),
        (publishable, "pk_test_"),
    ]:
        if not value.startswith(prefix) or "replace" in value or "fixture" in value:
            raise RuntimeError(
                "Stripeテストキーの仮設定を置き換えてから実行してください。"
            )
    # A macOS build is reviewable, but Azure's runtime bundle must be built on Linux.
    if sys.platform != "linux" and not args.configure_only:
        raise RuntimeError(
            "FrontendはLinuxでビルド・配布してください。GitHub ActionsまたはLinux環境で実行します。"
        )
    for part in () if args.configure_only else ("backend", "frontend"):
        if not (ROOT / f".release/{part}.zip").exists():
            raise RuntimeError("先に配布ZIPを作成してください。")
    run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://management.azure.com/",
            "--query",
            "expiresOn",
            "-o",
            "tsv",
        ]
    )
    available = json.loads(
        run(["az", "webapp", "list-runtimes", "--os", "linux", "-o", "json"])
    )
    candidates = []
    for runtime in available:
        if isinstance(runtime, str):
            candidates.append(runtime)
        elif (
            isinstance(runtime, dict)
            and runtime.get("runtime")
            and runtime.get("version")
        ):
            candidates.append(f"{runtime['runtime']}:{runtime['version']}")
    runtimes = {}
    for part, required in (("backend", "PYTHON:3.12"), ("frontend", "NODE:24LTS")):
        expected = required.replace("-", "").lower()
        match = next(
            (
                value
                for value in candidates
                if value.replace("|", ":").replace("-", "").lower() == expected
            ),
            None,
        )
        if match is None:
            raise RuntimeError(
                f"Azureで必要なランタイム {required} が確認できませんでした。"
            )
        runtimes[part] = match
    if args.create:
        run(
            [
                "az",
                "group",
                "create",
                "--name",
                args.resource_group,
                "--location",
                "japaneast",
            ]
        )
        existing_plan = run(
            [
                "az",
                "appservice",
                "plan",
                "show",
                "--resource-group",
                args.resource_group,
                "--name",
                args.plan,
            ],
            allow_missing=True,
        )
        if (
            existing_plan is not None
            and json.loads(existing_plan).get("sku", {}).get("name") != "F1"
        ):
            raise RuntimeError(
                "指定した既存プランがF1ではありません。対象を確認してください。"
            )
        if existing_plan is None:
            run(
                [
                    "az",
                    "appservice",
                    "plan",
                    "create",
                    "--resource-group",
                    args.resource_group,
                    "--name",
                    args.plan,
                    "--is-linux",
                    "--sku",
                    "F1",
                ]
            )
    for part, name, runtime in [
        ("backend", args.backend, runtimes["backend"]),
        ("frontend", args.frontend, runtimes["frontend"]),
    ]:
        existing = run(
            [
                "az",
                "webapp",
                "show",
                "--resource-group",
                args.resource_group,
                "--name",
                name,
            ],
            allow_missing=True,
        )
        if existing is None:
            if not args.create:
                raise RuntimeError(
                    "Web Appが未作成です。対象を確認して--createを付けてください。"
                )
            run(
                [
                    "az",
                    "webapp",
                    "create",
                    "--resource-group",
                    args.resource_group,
                    "--plan",
                    args.plan,
                    "--name",
                    name,
                    "--runtime",
                    runtime,
                ]
            )
        run(
            [
                "az",
                "webapp",
                "update",
                "--resource-group",
                args.resource_group,
                "--name",
                name,
                "--https-only",
                "true",
            ]
        )
        run(
            [
                "az",
                "webapp",
                "config",
                "set",
                "--resource-group",
                args.resource_group,
                "--name",
                name,
                "--startup-file",
                "bash startup.sh" if part == "backend" else "node server.js",
            ]
        )
    front_url, back_url = (
        f"https://{args.frontend}.azurewebsites.net",
        f"https://{args.backend}.azurewebsites.net",
    )
    keys = [
        "APP_ENV",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_SSL",
        "JWT_SECRET",
        "QR_SECRET",
        "BFF_SHARED_SECRET",
        "JOB_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "FRONTEND_BASE_URL",
        "MAIL_MODE",
        "DEV_TOOLS_ENABLED",
        "OVERDUE_POLICY_TEXT",
        "LOG_LEVEL",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "MAIL_FROM",
    ]
    raw = config.model_dump()
    backend_values = {}
    for key in keys:
        value = raw.get(key.lower())
        if value is not None:
            backend_values[key] = (
                value.get_secret_value()
                if hasattr(value, "get_secret_value")
                else str(value).lower()
                if isinstance(value, bool)
                else str(value)
            )
    if config.database_url:
        backend_values["DATABASE_URL"] = config.database_url.get_secret_value()
    backend_values.update(
        APP_ENV="azure-test",
        FRONTEND_BASE_URL=front_url,
        SCM_DO_BUILD_DURING_DEPLOYMENT="1",
        DEV_TOOLS_ENABLED="true",
    )
    frontend_values = {
        "BACKEND_BASE_URL": back_url,
        "FRONTEND_BASE_URL": front_url,
        "BFF_SHARED_SECRET": config.bff_shared_secret.get_secret_value(),
        "HOSTNAME": "0.0.0.0",
        "SCM_DO_BUILD_DURING_DEPLOYMENT": "false",
        "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY": publishable,
        "NEXT_PUBLIC_DEV_TOOLS_ENABLED": "true",
    }
    with tempfile.TemporaryDirectory(prefix="pickup-deploy-") as directory:
        folder = Path(directory)
        for part, name, values in [
            ("backend", args.backend, backend_values),
            ("frontend", args.frontend, frontend_values),
        ]:
            path = settings_file(folder, part + ".json", values)
            run(
                [
                    "az",
                    "webapp",
                    "config",
                    "appsettings",
                    "set",
                    "--resource-group",
                    args.resource_group,
                    "--name",
                    name,
                    "--settings",
                    "@" + str(path),
                ]
            )
            if not args.configure_only:
                run(
                    [
                        "az",
                        "webapp",
                        "deploy",
                        "--resource-group",
                        args.resource_group,
                        "--name",
                        name,
                        "--src-path",
                        str(ROOT / f".release/{part}.zip"),
                        "--type",
                        "zip",
                    ]
                )
    if args.configure_github:
        for part, name in [("BACKEND", args.backend), ("FRONTEND", args.frontend)]:
            ident = json.loads(
                run(
                    [
                        "az",
                        "webapp",
                        "show",
                        "--resource-group",
                        args.resource_group,
                        "--name",
                        name,
                    ]
                )
            )["id"]
            run(
                [
                    "az",
                    "resource",
                    "update",
                    "--ids",
                    ident + "/basicPublishingCredentialsPolicies/scm",
                    "--set",
                    "properties.allow=true",
                ]
            )
            profile = run(
                [
                    "az",
                    "webapp",
                    "deployment",
                    "list-publishing-profiles",
                    "--resource-group",
                    args.resource_group,
                    "--name",
                    name,
                    "--xml",
                    "--output",
                    "tsv",
                ]
            )
            run(
                [
                    "gh",
                    "secret",
                    "set",
                    f"AZURE_WEBAPP_PUBLISH_PROFILE_{part}",
                    "--repo",
                    args.repository,
                ],
                input_text=profile,
            )
            run(
                [
                    "gh",
                    "variable",
                    "set",
                    f"AZURE_WEBAPP_NAME_{part}",
                    "--repo",
                    args.repository,
                    "--body",
                    name,
                ]
            )
        for key, value in {
            "BACKEND_URL": back_url,
            "JOB_SECRET": config.job_secret.get_secret_value(),
            "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY": publishable,
        }.items():
            run(
                ["gh", "secret", "set", key, "--repo", args.repository],
                input_text=value,
            )
        run(
            [
                "gh",
                "variable",
                "set",
                "DEPLOYMENT_ENABLED",
                "--repo",
                args.repository,
                "--body",
                "false" if args.configure_only else "true",
            ]
        )
    print(
        json.dumps(
            {
                "frontend": front_url,
                "backend": back_url,
                "databaseChanged": False,
                "artifactsDeployed": not args.configure_only,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - Never print SDK/config exceptions containing secrets.
        print(
            str(exc)
            if isinstance(exc, RuntimeError)
            else "デプロイに失敗しました。設定と認証を確認してください。",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
