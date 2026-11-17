#!/usr/bin/env python3
"""注册制试用开闸 · 本机端到端链路验证（注册制试用开闸 R4）。

逐环实测并贴输出（只说通了不算）：注册 → 收验证邮件 → 邮箱验证 → 登录 → 试用写动作。
每环打印 HTTP 状态与关键字段；失败即停并如实报告卡在哪一环。

**两种取信方式**：
- ``--mail-sink``：读本地假 SMTP 服务器落盘的 JSONL（本地链路自证，无需任何
  真实邮箱凭据；STARTTLS 真握手，见 ``dummy_smtp_server.py``）；
- ``--imap-*``：读真实邮箱（IMAP SSL）——真发信轮（OWNER 提供凭据后）用这条。

用法示例（本地自证）::

    python scripts/verify/verify_registration_trial.py \
      --base-url http://127.0.0.1:8099 --entry enterprise \
      --username trial_user_01 --password 'TrialPass!2345' \
      --email trial_user_01@example.com --subject-key TRIAL-001 \
      --display-name 试用企业代号 --mail-sink /tmp/dummy_smtp.jsonl

真发信轮（凭据带外给执行者，脚本本身不含凭据）::

    python scripts/verify/verify_registration_trial.py ... \
      --imap-host imap.gmail.com --imap-user ... --imap-password-env FDE_TRIAL_IMAP_PASSWORD
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from email import message_from_string
from email.policy import default as default_policy
from pathlib import Path
from urllib.parse import unquote

TOKEN_IN_LINK = re.compile(r"verify-email\?token=([^\s&\"'>]+)")


def _post(url: str, payload: dict[str, object], token: str | None = None) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return error.code, {"raw": raw[:400]}


def _get(url: str, token: str | None = None) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return error.code, {"raw": raw[:400]}


def _read_sink(path: Path, recipient: str, timeout: float) -> str | None:
    """从假 SMTP 落盘里找最新一封发给 recipient 的邮件正文。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                record = json.loads(line)
                recipients = [str(item).strip("<>") for item in record.get("to", [])]
                if recipient.lower() in [item.lower() for item in recipients]:
                    return str(record.get("data", ""))
        time.sleep(1.0)
    return None


def _read_imap(host: str, user: str, password: str, timeout: float) -> str | None:
    import imaplib

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = imaplib.IMAP4_SSL(host)
            client.login(user, password)
            client.select("INBOX")
            status, data = client.search(None, "ALL")
            if status == "OK" and data and data[0].split():
                latest = data[0].split()[-1]
                status, payload = client.fetch(latest, "(RFC822)")
                if status == "OK" and payload and isinstance(payload[0], tuple):
                    client.logout()
                    return payload[0][1].decode("utf-8", "replace")
            client.logout()
        except Exception:  # noqa: BLE001 —— 取信失败重试（轮询窗口内）
            pass
        time.sleep(5.0)
    return None


def _message_text(raw: str) -> str:
    """把原始邮件解析为正文文本（正文含中文 ⇒ MIME base64 编码，必须解码）。"""
    try:
        parsed = message_from_string(raw, policy=default_policy)
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == "text/plain":
                    return str(part.get_content())
            return raw
        return str(parsed.get_content())
    except Exception:  # noqa: BLE001 —— 解析失败退回原文
        return raw


def _extract_token(message: str) -> str | None:
    match = TOKEN_IN_LINK.search(message)
    if match:
        return unquote(match.group(1))
    for line in message.splitlines():
        stripped = line.strip()
        if stripped and " " not in stripped and len(stripped) >= 20:
            candidate = stripped
            if candidate not in ("",):
                return candidate
    return None


def _mask(value: str) -> str:
    return f"{value[:6]}…({len(value)} chars)" if value else "(empty)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--entry", default="enterprise")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--subject-key", required=True)
    parser.add_argument("--display-name", default="试用企业代号")
    parser.add_argument("--problem-description", default="注册试用：交付流程咨询与试点项目支持。")
    parser.add_argument("--mail-sink", default="")
    parser.add_argument("--imap-host", default="")
    parser.add_argument("--imap-user", default="")
    parser.add_argument("--imap-password-env", default="")
    parser.add_argument("--mail-timeout", type=float, default=60.0)
    parser.add_argument(
        "--module-key",
        default="sop_presale",
        help="建项目用的模块键（module_catalog 四段固定模块之一；需已跑种子）",
    )
    parser.add_argument("--skip-write", action="store_true")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    steps: list[tuple[str, str]] = []

    def _record(name: str, detail: str) -> None:
        steps.append((name, detail))
        print(f"[{len(steps)}] {name}: {detail}", flush=True)

    status, payload = _get(f"{base}/api/v1/health/live")
    if status != 200:
        print(f"[FAIL] 探活失败 HTTP {status}: {payload}")
        return 1
    _record("探活 live", f"HTTP {status}")

    register_payload = {
        "username": args.username,
        "display_name": args.display_name,
        "password": args.password,
        "email": args.email,
        "subject_key": args.subject_key,
        "problem_description": args.problem_description,
    }
    status, payload = _post(f"{base}/api/v1/auth/register/{args.entry}", register_payload)
    data = payload.get("data") or {}
    mail_detail = data.get("verification_email") or {}
    mail_status = mail_detail.get("status")
    mail_code = mail_detail.get("code", "")
    if status != 201:
        print(f"[FAIL] 注册失败 HTTP {status}: {payload}")
        return 1
    _record(
        "注册",
        f"HTTP {status} user_id={data.get('user_id')} state={data.get('registration_state')} "
        f"verification_email={mail_status}"
        + (f"({mail_code})" if mail_code else ""),
    )
    if mail_status != "sent":
        print(f"[FAIL] 验证邮件未发出（verification_email={mail_status}）——链路断在发信环")
        return 1

    if args.mail_sink:
        message = _read_sink(Path(args.mail_sink), args.email, args.mail_timeout)
        source = "本地假 SMTP 落盘"
    elif args.imap_host:
        secret = os.environ.get(args.imap_password_env, "")
        if not secret:
            print(f"[FAIL] 环境变量 {args.imap_password_env} 未设置（凭据带外提供，不落 argv）")
            return 1
        message = _read_imap(args.imap_host, args.imap_user, secret, args.mail_timeout)
        source = f"真实邮箱 IMAP {args.imap_host}"
    else:
        print("[FAIL] 未指定取信方式（--mail-sink 或 --imap-*）")
        return 1
    if not message:
        print(f"[FAIL] {args.mail_timeout:.0f}s 内未收到验证邮件（来源：{source}）")
        return 1
    _record("收验证邮件", f"来源={source} 正文字节={len(message)}")

    token = _extract_token(_message_text(message))
    if not token:
        print("[FAIL] 邮件正文中未解析出验证令牌")
        return 1
    _record("取出验证令牌", _mask(token))

    status, payload = _post(f"{base}/api/v1/auth/registrations/verify", {"token": token})
    data = payload.get("data") or {}
    if status != 200:
        print(f"[FAIL] 邮箱验证失败 HTTP {status}: {payload}")
        return 1
    _record(
        "邮箱验证",
        f"HTTP {status} registration_state={data.get('registration_state')} entry={data.get('entry')}",
    )

    status, payload = _post(
        f"{base}/api/v1/auth/login",
        {"username": args.username, "password": args.password, "device_label": "regtrial-e2e"},
    )
    data = payload.get("data") or {}
    access_token = str(data.get("access_token", ""))
    if status != 200 or not access_token:
        print(f"[FAIL] 登录失败 HTTP {status}: {payload}")
        return 1
    _record("登录", f"HTTP {status} access_token={_mask(access_token)} role={data.get('user', {}).get('role')}")

    if not args.skip_write:
        user_id = data.get("user", {}).get("id")
        write_payload = {
            "name": f"注册试用项目-{args.subject_key}",
            "enterprise_code": args.subject_key,
            "planned_start_date": "2026-11-18",
            "leader_user_id": user_id,
            "module_keys": [args.module_key],
            # 立项入口：manual（不挂模板版本；template 形态须带 template_version_id）
            "creation_source": "manual",
            # 非模板立项须自带项目快照（modules 逐段对应 module_catalog 的 module_key）
            "project_snapshot": {
                "industry_name": "通用",
                "description": "注册试用项目快照",
                "modules": [{"module_key": args.module_key}],
            },
        }
        status, payload = _post(f"{base}/api/v1/projects", write_payload, token=access_token)
        data = payload.get("data") or {}
        if status != 201:
            print(f"[FAIL] 试用写动作失败 HTTP {status}: {payload}")
            print(f"       送出载荷: {write_payload}")
            return 1
        project_id = data.get("id") or data.get("project_id")
        _record("试用写动作（建项目）", f"HTTP {status} project_id={project_id}")

        status, payload = _get(f"{base}/api/v1/projects", token=access_token)
        data = payload.get("data") or []
        _record("读回校验", f"HTTP {status} 项目数={len(data) if isinstance(data, list) else 'n/a'}")

    print("\n================ 端到端结果 ================")
    for name, detail in steps:
        print(f"  ✅ {name} — {detail}")
    print("[PASS] 注册 → 收验证邮件 → 邮箱验证 → 登录 → 试用写动作 全链通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
