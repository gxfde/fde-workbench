#!/usr/bin/env python3
"""Verify public live readiness of diag.fde18.com (D-3 independent light deployment)
and CTA wiring on fde18.com/diagnosis-samples/.

Read-only network verification tool (goal-sprint r5 · T-14b closeout):
1. DNS resolution for diag.fde18.com
2. HTTP :80 -> 301 https://diag.fde18.com/
3. HTTPS :443 TLS certificate validity + SPA root + CSP header
4. Public diagnostic questionnaire API (200) & registration gate isolation (404)
5. Main workbench app.fde18.com diagnostic gate isolation (404)
6. Official site fde18.com/diagnosis-samples/ holds diag.fde18.com CTAs and zero app.fde18.com links
"""
from __future__ import annotations

import json
import socket
import ssl
import sys
import urllib.error
import urllib.request

EXPECTED_IP = "141.95.33.198"
DIAG_ENTRY_HREF = 'href="https://diag.fde18.com/#diagnostics"'
DIAG_SAMPLE_HREF = 'href="https://diag.fde18.com/#diagnostics/sample"'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _request(url: str, *, method: str = "GET", ctx: ssl.SSLContext | None = None) -> tuple[int, dict[str, str], str]:
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    data = b"{}" if method == "POST" else None
    headers = {"User-Agent": "fde-verify-diag-public-live/1.0"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body


def main() -> int:
    failures: list[str] = []
    ctx = ssl.create_default_context()

    # 1. DNS
    ips = sorted({row[4][0] for row in socket.getaddrinfo("diag.fde18.com", 443, socket.AF_INET)})
    if EXPECTED_IP not in ips:
        failures.append(f"DNS mismatch: expected {EXPECTED_IP} in {ips}")
    print(f"[1/6] DNS diag.fde18.com -> {ips}")

    # 2. HTTP 80 -> 301 HTTPS
    c80, h80, _ = _request("http://diag.fde18.com/")
    loc80 = h80.get("location", "")
    if c80 != 301 or loc80 != "https://diag.fde18.com/":
        failures.append(f"HTTP:80 redirect unexpected: status={c80} location={loc80!r}")
    print(f"[2/6] HTTP :80 -> {c80} Location={loc80}")

    # 3. HTTPS 443 SPA + TLS cert + CSP
    with (
        socket.create_connection(("diag.fde18.com", 443), timeout=10) as raw_sock,
        ctx.wrap_socket(raw_sock, server_hostname="diag.fde18.com") as tls_sock,
    ):
        cert = tls_sock.getpeercert() or {}
    not_after = cert.get("notAfter", "")
    c443, h443, body443 = _request("https://diag.fde18.com/", ctx=ctx)
    if c443 != 200 or "<title>" not in body443 or "Stopped" in body443 or "content-security-policy" not in h443:
        failures.append(f"HTTPS root invalid: status={c443} len={len(body443)} csp={'content-security-policy' in h443}")
    print(f"[3/6] HTTPS :443 -> {c443} len={len(body443)} cert_notAfter={not_after!r}")

    # 4. Questionnaire 200 + ready 200 + registration gate 404
    cq, _, bq = _request("https://diag.fde18.com/api/v1/diagnostics/questionnaire", ctx=ctx)
    cr, _, br = _request("https://diag.fde18.com/api/v1/health/ready", ctx=ctx)
    creg, _, _ = _request("https://diag.fde18.com/api/v1/register/enterprise", method="POST", ctx=ctx)
    ready_ok = cr == 200 and json.loads(br).get("data", {}).get("database") == "ok"
    if cq != 200 or len(bq) < 1000 or not ready_ok or creg != 404:
        failures.append(f"diag API gates unexpected: questionnaire={cq}({len(bq)}B) ready={cr} register={creg}")
    print(f"[4/6] diag API -> questionnaire={cq}({len(bq)}B) ready={cr} register_gate={creg}")

    # 5. Main workbench diagnostic gate remains closed (404)
    capp_q, _, _ = _request("https://app.fde18.com/api/v1/diagnostics/questionnaire", ctx=ctx)
    if capp_q != 404:
        failures.append(f"app.fde18.com diagnostic gate expected 404, got {capp_q}")
    print(f"[5/6] app.fde18.com diagnostic gate -> {capp_q}")

    # 6. Official site CTA anchors & zero app.fde18.com leakage
    cw, _, bw = _request("https://fde18.com/diagnosis-samples/", ctx=ctx)
    has_entry = DIAG_ENTRY_HREF in bw
    has_sample = DIAG_SAMPLE_HREF in bw
    has_app = "app.fde18.com" in bw
    if cw != 200 or not has_entry or not has_sample or has_app:
        failures.append(
            f"fde18.com/diagnosis-samples/ check failed: status={cw} entry={has_entry} sample={has_sample} app_leak={has_app}"
        )
    print(f"[6/6] fde18.com/diagnosis-samples/ -> {cw} entry={has_entry} sample={has_sample} zero_app_link={not has_app}")

    if failures:
        for item in failures:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1
    print("VERIFY-R5-DIAG-PUBLIC-LIVE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
