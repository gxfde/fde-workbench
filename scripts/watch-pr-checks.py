#!/usr/bin/env python3
"""守望 PR 的 CI check-runs 收敛。

用途：合并前确认 PR 的 4 个 CI job（desktop / server-tests /
secrets-scan / pseudonymization）全部跑完且为绿。

为什么需要这个脚本（踩坑记录）：

  · **不能用 `GET /actions/runs?head_sha=` 轮询**：PR 走 API 建分支+提交+开 PR
    （不经 git push）时，该索引会长时间返回 0 条。
  · **不能用 `GET /actions/runs?branch=` 轮询**：会间歇性返回空列表——同一轮
    轮询里从「总 21 / 未完成 16」闪成「总 0 / 未完成 0」。
  · **唯一可靠**：`GET /commits/<sha>/check-runs`（同名 job 按 started_at 取最大）。

  ⚠️ **比端点更重要的纪律：空结果 ≠ 收敛。**
  守望循环里若写 `if not jobs: print('全部结束')`，一次索引抖动就会**误判成绿**
  ——这是最危险的假绿。本脚本显式区分「空列表」与「已收敛」，空则重试并计数；
  只有「存在 check-run 且全部 completed」才收口。

用法：
    python3 scripts/watch-pr-checks.py <PR号> [--repo owner/name] [--interval 20]

退出码：0 = 全绿收敛；1 = 有失败项；2 = 超时未收敛；3 = 用法错误。
"""
import argparse
import json
import subprocess
import sys
import time

DEFAULT_REPO = "caishide/fde-workbench"
# 仓库 CI 的 4 个 job（.github/workflows/ci.yml）。用于在收敛前核对齐全性——
# 少一个 job 也应视为未就绪，而不是「反正没失败就算过」。
EXPECTED_JOBS = {"desktop", "server-tests", "secrets-scan", "pseudonymization"}


def run_gh(args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 失败: {out.stderr.strip()}")
    return out.stdout


def head_sha(pr, repo):
    data = json.loads(run_gh(["pr", "view", str(pr), "--repo", repo,
                               "--json", "headRefOid"]))
    return data["headRefOid"]


def fetch_check_runs(sha, repo):
    data = json.loads(run_gh(
        ["api", f"/repos/{repo}/commits/{sha}/check-runs?per_page=100"]))
    return data.get("check_runs", [])


def latest_by_job(runs):
    """同名 job 可能有多个 run（重跑），按 started_at 取最新。"""
    latest = {}
    for run in runs:
        name = run["name"]
        current = latest.get(name)
        if current is None or run["started_at"] > current["started_at"]:
            latest[name] = run
    return latest


def main():
    parser = argparse.ArgumentParser(description="守望 PR 的 CI check-runs 收敛")
    parser.add_argument("pr", help="PR 编号")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name")
    parser.add_argument("--interval", type=int, default=20, help="轮询间隔秒数")
    parser.add_argument("--max-rounds", type=int, default=90, help="最大轮次")
    args = parser.parse_args()

    sha = head_sha(args.pr, args.repo)
    print(f"[watch] PR #{args.pr} repo={args.repo} sha={sha[:12]}")

    empty_rounds = 0
    for round_no in range(1, args.max_rounds + 1):
        runs = fetch_check_runs(sha, args.repo)
        if not runs:
            empty_rounds += 1
            print(f"[{round_no}] 空列表（索引抖动，**不是**收敛）连续 {empty_rounds} 次 → 继续等待")
            time.sleep(args.interval)
            continue

        empty_rounds = 0
        latest = latest_by_job(runs)
        rows = [(name, run["status"], run.get("conclusion") or "-")
                for name, run in sorted(latest.items())]
        pending = [row for row in rows if row[1] != "completed"]
        for name, status, conclusion in rows:
            print(f"[{round_no}] {name:22s} {status:12s} {conclusion}")

        if not pending:
            missing = EXPECTED_JOBS - set(latest)
            if missing:
                print(f"[watch] 缺少 CI job {sorted(missing)} → 尚未就绪，继续等待")
                time.sleep(args.interval)
                continue
            failed = [row for row in rows
                      if row[2] not in ("success", "skipped", "neutral")]
            if failed:
                print(f"[watch] 全部 completed，但有失败项: {failed}")
                return 1
            print("[watch] 全部 completed 且 4 个 job 齐全、全绿")
            return 0

        time.sleep(args.interval)

    print("[watch] 超出最大轮次，未收敛")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"[watch] {error}")
        sys.exit(3)
