"""Read-only pre-push checks. Never print secret values or matching source lines."""

import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(rb"sk_(?:live|test)_[A-Za-z0-9]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{60,}"),
    re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{40,}"
    ),
)
KEYS = (
    "DATABASE_PASSWORD",
    "DATABASE_USER",
    "JWT_SECRET",
    "QR_SECRET",
    "BFF_SHARED_SECRET",
    "JOB_SECRET",
    "SEED_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SMTP_PASSWORD",
    "SMTP_USERNAME",
)


def git(*args, input=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, input=input)


def main():
    values = dotenv_values(ROOT / "backend/.env")
    frontend_values = dotenv_values(ROOT / "frontend/.env.local")
    secrets = [
        source[key].encode()
        for source in (values, frontend_values)
        for key in KEYS
        if source.get(key) and "replace_me" not in source[key]
    ]
    if not values.get("DATABASE_PASSWORD") or not values.get("SEED_PASSWORD"):
        print("実際のDB・デモ用パスワードが未設定のため照合を完了できません。")
        return 1
    findings = set()

    def check(label, data):
        if any(value in data for value in secrets) or any(
            p.search(data) for p in PATTERNS
        ):
            findings.add(label)

    files = set(
        filter(
            None,
            git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
            .decode()
            .split("\0"),
        )
    )
    for name in files:
        path = ROOT / name
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.add(name)
        if path.is_file():
            check(name, path.read_bytes())
    # Inspect the index separately: staged content can differ from the working tree.
    index_blobs = set()
    for item in git("ls-files", "--stage", "-z").decode().split("\0"):
        if not item:
            continue
        metadata, name = item.split("\t", 1)
        _, oid, _ = metadata.split()
        index_blobs.add(oid)
        check("index:" + name, git("cat-file", "blob", oid))
    objects = {}
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        oid, _, name = line.partition(" ")
        objects[oid] = name
    header = (
        git(
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
            input=("\n".join(objects) + "\n").encode(),
        )
        .decode()
        .splitlines()
    )
    blob_count = 0
    for item in header:
        oid, kind = item.split()
        if kind == "blob":
            check("history:" + objects[oid], git("cat-file", "blob", oid))
            blob_count += 1
    for name in ("backend/.env", "frontend/.env.local", ".migration-backups"):
        if (
            subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, check=False).returncode
            != 0
        ):
            findings.add("ignore:" + name)
    print(f"確認ファイル: {len(files)} / 履歴内のファイル内容: {blob_count}")
    print(f"実際の秘密値とパターンの照合: {len(findings)}件検出")
    for finding in sorted(findings):
        print("要確認ファイル:", finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
