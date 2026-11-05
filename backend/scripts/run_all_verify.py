"""P1~P10 一键验收：串行执行 backend/scripts/verify_p*.py，汇总结果。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\run_all_verify.py
    .venv\\Scripts\\python.exe scripts\\run_all_verify.py --only p8 p9 p10

约定：每个 verify 脚本末行输出 "PN 验收：X/Y 通过"，全部 exit 0 则本脚本 exit 0。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
LOG_DIR = Path(os.environ.get("TEMP", ".")) / "erecords_verify"
SUMMARY_RE = re.compile(r"(P\d+)\s*验收：\s*(\d+)/(\d+)\s*通过")


def discover(only: list[str] | None) -> list[Path]:
    files = sorted(SCRIPTS.glob("verify_p*.py"), key=lambda p: int(re.search(r"p(\d+)", p.stem).group(1)))
    if only:
        want = {f"p{v.lstrip('pP')}" for v in only}
        files = [f for f in files if f.stem.split("_")[1] in want]
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="只跑指定阶段，如 p9 p10")
    ap.add_argument("--fail-fast", action="store_true", help="首个失败即停止")
    args = ap.parse_args()

    files = discover(args.only)
    if not files:
        print("未找到 verify_p*.py", flush=True)
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    rows: list[tuple[str, str, str, float]] = []
    failed = 0

    for f in files:
        stage = re.search(r"(p\d+)", f.stem).group(1).upper()
        log_path = LOG_DIR / f"{f.stem}.log"
        print(f"\n{'=' * 62}\n>>> {stage}  {f.name}\n{'=' * 62}", flush=True)
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8", errors="ignore") as fp:
            proc = subprocess.run([sys.executable, str(f)], cwd=str(BACKEND), env=env,
                                  stdout=fp, stderr=subprocess.STDOUT)
        cost = time.time() - t0
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        # 原样回显（过长时只留尾部 40 行）
        lines = text.splitlines()
        tail = lines if len(lines) <= 60 else ["...（前略，完整日志见 " + str(log_path) + "）"] + lines[-40:]
        print("\n".join(tail), flush=True)

        m = None
        for line in reversed(lines):
            m = SUMMARY_RE.search(line)
            if m:
                break
        if proc.returncode == 0:
            rows.append((stage, "PASS", m.group(2) + "/" + m.group(3) if m else "-", cost))
        else:
            failed += 1
            rows.append((stage, "FAIL", m.group(2) + "/" + m.group(3) if m else "崩溃/未输出汇总", cost))
            if args.fail_fast:
                print(f"\n[--fail-fast] {stage} 失败，中止。", flush=True)
                break

    print("\n" + "=" * 62, flush=True)
    print(f"{'阶段':<6}{'结果':<8}{'通过项':<12}{'耗时':<8}", flush=True)
    print("-" * 62, flush=True)
    for stage, status, ratio, cost in rows:
        print(f"{stage:<6}{status:<8}{ratio:<12}{cost:>6.1f}s", flush=True)
    print("-" * 62, flush=True)
    total = len(rows)
    passed = total - failed
    print(f"全阶段验收：{passed}/{total} 阶段通过" + ("" if failed == 0 else f"，失败 {failed} 个"), flush=True)
    if failed:
        print("失败阶段的完整日志：" + ", ".join(str(LOG_DIR / f"{f.stem}.log") for f in files), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
