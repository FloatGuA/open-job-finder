"""Install the repo's git hooks.

.git/hooks is not version-controlled, so the hook itself cannot live in the repo
and be active -- every clone has to install it. This script writes a thin shell
shim that delegates to scripts/precommit_pii_scan.py, so the actual logic stays
in git (and stays testable).

    python code/scripts/install_hooks.py
    python code/scripts/install_hooks.py --uninstall
"""
import argparse
import stat
import sys
from pathlib import Path

HOOK_NAME = "pre-commit"
MARKER = "# open-job-finder pii guard"

HOOK_BODY = f"""#!/bin/sh
{MARKER}
# Blocks commits containing personal data from the private job database.
# Location-based .gitignore rules cannot protect PROGRESS.md (it must be
# committed), so content is scanned instead. See scripts/precommit_pii_scan.py.
# Bypass with: git commit --no-verify
python code/scripts/precommit_pii_scan.py || exit 1
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="安装/卸载 git hooks")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print(f"找不到 {hooks_dir}（不是 git 仓库？）", file=sys.stderr)
        return 1

    hook_path = hooks_dir / HOOK_NAME

    if args.uninstall:
        if hook_path.exists() and MARKER in hook_path.read_text(encoding="utf-8", errors="replace"):
            hook_path.unlink()
            print(f"已卸载 {hook_path}")
        else:
            print("未安装本仓库的 hook，未做改动")
        return 0

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if MARKER not in existing:
            # Never clobber someone else's hook silently.
            print(f"{hook_path} 已存在且不是本仓库的 hook，未覆盖。", file=sys.stderr)
            print("请手动把下面一行加进去：", file=sys.stderr)
            print("  python code/scripts/precommit_pii_scan.py || exit 1", file=sys.stderr)
            return 1

    hook_path.write_text(HOOK_BODY, encoding="utf-8", newline="\n")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"已安装 {hook_path}")
    print("提交时会自动扫描个人隐私数据；确认误报可用 git commit --no-verify 跳过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
