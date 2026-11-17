#!/usr/bin/env python3
"""本地假 SMTP 服务器（注册制试用开闸 R4 端到端备料用）。

用途：在**不依赖任何真实邮箱凭据**的前提下，把注册面验证邮件的完整链路跑通
（发信通道 → STARTTLS → 账号口令登录 → 邮件落盘 → 取出验证令牌）。真发信
（SMTP 真服务器 + 真口令）由 OWNER 备料后另行执行，本脚本只服务本地链路。

关键点：
- **支持 STARTTLS**：服务端通道要求 TLS（STARTTLS 不可用即失败、不回落明文），
  因此这里必须真的握手；证书由调用方给（自签证书 + 调用方把 CA 交给客户端
  的 ``SSL_CERT_FILE``）。
- 邮件落盘为 JSONL（一行一封），供 ``verify_registration_trial.py`` 读取。

环境变量：
  DUMMY_SMTP_HOST（默认 127.0.0.1）／DUMMY_SMTP_PORT（默认 1025）／
  DUMMY_SMTP_SINK（默认 /tmp/dummy_smtp.jsonl）／
  DUMMY_SMTP_CERT＋DUMMY_SMTP_KEY（STARTTLS 证书与私钥；缺省则不提供 STARTTLS）

用法：``python scripts/verify/dummy_smtp_server.py``
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
from pathlib import Path

HOST = os.environ.get("DUMMY_SMTP_HOST", "127.0.0.1")
PORT = int(os.environ.get("DUMMY_SMTP_PORT", "1025"))
SINK = Path(os.environ.get("DUMMY_SMTP_SINK", "/tmp/dummy_smtp.jsonl"))
CERT = os.environ.get("DUMMY_SMTP_CERT", "")
KEY = os.environ.get("DUMMY_SMTP_KEY", "")


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    envelope: dict[str, object] = {"from": "", "to": [], "data": "", "tls": False}
    writer.write(b"220 dummy.smtp ESMTP ready\r\n")
    await writer.drain()
    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode("utf-8", "replace").strip()
        upper = text.upper()
        if upper.startswith("EHLO"):
            writer.write(b"250-dummy.smtp\r\n")
            if not envelope["tls"] and CERT:
                writer.write(b"250-STARTTLS\r\n")
            writer.write(b"250-AUTH PLAIN LOGIN\r\n")
            writer.write(b"250 SIZE 10485760\r\n")
        elif upper.startswith("HELO"):
            writer.write(b"250 dummy.smtp\r\n")
        elif upper.startswith("AUTH PLAIN"):
            # 明文口令只进内存管道（本地假服务器，不落盘、不回执）
            envelope["auth"] = "PLAIN"
            writer.write(b"235 Authentication successful\r\n")
        elif upper.startswith("AUTH LOGIN"):
            envelope["auth"] = "LOGIN"
            writer.write(b"334 VXNlcm5hbWU6\r\n")
            await reader.readline()  # base64 用户名
            writer.write(b"334 UGFzc3dvcmQ6\r\n")
            await reader.readline()  # base64 口令
            writer.write(b"235 Authentication successful\r\n")
        elif upper.startswith("STARTTLS"):
            if not CERT:
                writer.write(b"502 STARTTLS not available\r\n")
            else:
                writer.write(b"220 Ready to start TLS\r\n")
                await writer.drain()
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(CERT, KEY)
                await writer.start_tls(context)
                envelope["tls"] = True
        elif upper.startswith("MAIL FROM:"):
            envelope["from"] = text.split(":", 1)[1].strip()
            writer.write(b"250 OK\r\n")
        elif upper.startswith("RCPT TO:"):
            recipients = envelope["to"]
            assert isinstance(recipients, list)
            recipients.append(text.split(":", 1)[1].strip())
            writer.write(b"250 OK\r\n")
        elif upper.startswith("DATA"):
            writer.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            await writer.drain()
            chunks: list[bytes] = []
            while True:
                data_line = await reader.readline()
                if not data_line:
                    break
                if data_line.strip() == b".":
                    break
                if data_line.startswith(b".."):
                    data_line = data_line[1:]
                chunks.append(data_line)
            envelope["data"] = b"".join(chunks).decode("utf-8", "replace")
            SINK.parent.mkdir(parents=True, exist_ok=True)
            with SINK.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            print(
                f"[dummy-smtp] captured from={envelope['from']} "
                f"to={envelope['to']} bytes={len(str(envelope['data']))} "
                f"tls={envelope['tls']}",
                flush=True,
            )
            envelope = {"from": "", "to": [], "data": "", "tls": envelope["tls"]}
            writer.write(b"250 OK: queued\r\n")
        elif upper.startswith("RSET"):
            envelope = {"from": "", "to": [], "data": "", "tls": envelope["tls"]}
            writer.write(b"250 OK\r\n")
        elif upper.startswith("NOOP"):
            writer.write(b"250 OK\r\n")
        elif upper.startswith("QUIT"):
            writer.write(b"221 Bye\r\n")
            await writer.drain()
            break
        else:
            writer.write(b"250 OK\r\n")
        await writer.drain()
    writer.close()


async def main() -> None:
    server = await asyncio.start_server(_handle, HOST, PORT)
    print(f"[dummy-smtp] listening on {HOST}:{PORT} sink={SINK} tls={'on' if CERT else 'off'}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[dummy-smtp] stopped", flush=True)
