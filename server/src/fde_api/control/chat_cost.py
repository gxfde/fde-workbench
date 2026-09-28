"""Conservative, source-labeled estimate of a completed DeepSeek Flash turn."""
from datetime import UTC, datetime
from decimal import Decimal

import requests


PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
PRICES_PEAK_PER_M = {
    "deepseek-flash": (Decimal("0.3"), Decimal("0.006"), Decimal("1.2")),
    "deepseek-v4.1-flash": (Decimal("0.3"), Decimal("0.006"), Decimal("1.2")),
    "deepseek-v4-flash": (Decimal("0.3"), Decimal("0.006"), Decimal("1.2")),
    "deepseek-v4-flash-vision-exp": (Decimal("0.3"), Decimal("0.006"), Decimal("1.2")),
    "deepseek-v4-pro": (Decimal("1.32"), Decimal("0.044"), Decimal("3.96")),
}


def estimate_chat_cost(provider_usage: dict) -> dict:
    calls = provider_usage.get("calls") if isinstance(provider_usage, dict) else None
    if not isinstance(provider_usage, dict) or not provider_usage.get("complete") or not isinstance(calls, list) or not calls:
        return {"cny_estimate": None, "note": "对话模型未提供完整、可核对的 Token 用量，费用不估算。"}
    if any(call.get("model") not in PRICES_PEAK_PER_M for call in calls):
        return {"cny_estimate": None, "note": "当前对话模型未配置已核实的单价，费用不估算。"}
    required = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    if any(any(type(call.get(key)) is not int or call[key] < 0 for key in required) for call in calls):
        return {"cny_estimate": None, "note": "缓存分项不完整，无法可靠折算对话模型费用。"}
    now = datetime.now(UTC)
    peak = now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)
    factor = Decimal("1") if peak else Decimal("0.5")
    usd = Decimal(0)
    for call in calls:
        input_price, hit_price, output_price = PRICES_PEAK_PER_M[call["model"]]
        usd += ((Decimal(call["input_tokens"] + call["cache_write_tokens"]) * input_price
                 + Decimal(call["cache_read_tokens"]) * hit_price
                 + Decimal(call["output_tokens"]) * output_price) * factor / Decimal(1_000_000))
    result = {"usd_estimate": str(usd), "cny_estimate": None, "price_source": PRICE_SOURCE,
              "pricing_band": "peak" if peak else "off_peak", "note": "按 2026-09-22 官方 DeepSeek 单价估算，非实际账单。"}
    try:
        response = requests.get("https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY", timeout=5)
        response.raise_for_status()
        value = response.json()
        rate = Decimal(str(value["rates"]["CNY"]))
        if not Decimal("1") < rate < Decimal("20"):
            raise ValueError("invalid_fx")
        result.update({"cny_estimate": str((usd * rate).quantize(Decimal("0.000001"))),
                       "usd_cny_rate": str(rate), "fx_date": value["date"],
                       "fx_source": "https://www.frankfurter.app/"})
    except (requests.RequestException, ValueError, TypeError, KeyError):
        result["note"] += " 汇率不可用，人民币金额暂无法核算。"
    return result
