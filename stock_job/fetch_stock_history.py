#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
ANCHOR = date(2026, 8, 14)
END_EXCLUSIVE = date(2026, 8, 15)
WINDOWS = {
    "6m": date(2026, 2, 14),
    "1y": date(2025, 8, 14),
    "18m": date(2025, 2, 14),
    "2y": date(2024, 8, 14),
}
HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

def epoch_at_jst_midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=JST).timestamp())

def request_json(symbol: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "period1": epoch_at_jst_midnight(WINDOWS["2y"]),
            "period2": epoch_at_jst_midnight(END_EXCLUSIVE),
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
    )
    last_error: Exception | None = None
    for attempt in range(7):
        for host in HOSTS:
            url = f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol)}?{params}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json,text/plain,*/*",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = resp.read()
                data = json.loads(payload.decode("utf-8"))
                chart = data.get("chart", {})
                if chart.get("error"):
                    raise RuntimeError(f"Yahoo chart error: {chart['error']}")
                if not chart.get("result"):
                    raise RuntimeError("Yahoo chart result is empty")
                return data
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                continue
        sleep_s = min(45.0, (2 ** attempt) + random.random() * 2.0)
        print(f"retry {attempt + 1}/7 for {symbol}: {last_error}; sleep {sleep_s:.1f}s", flush=True)
        time.sleep(sleep_s)
    raise RuntimeError(f"all Yahoo hosts failed for {symbol}: {last_error}")

def fmt_num(x: float | int | None) -> str:
    if x is None:
        return ""
    return f"{float(x):.6f}".rstrip("0").rstrip(".")

def summarize(code: str) -> dict[str, str]:
    symbol = f"{code}.T"
    out: dict[str, str] = {
        "code": code,
        "symbol": symbol,
        "close_2026_08_14": "",
        "low_6m": "",
        "low_6m_date": "",
        "low_1y": "",
        "low_1y_date": "",
        "low_18m": "",
        "low_18m_date": "",
        "low_2y": "",
        "low_2y_date": "",
        "first_date": "",
        "last_date": "",
        "row_count": "0",
        "split_events": "",
        "status": "",
        "error": "",
    }
    try:
        data = request_json(symbol)
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        quote_arr = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote_arr.get("close") or []
        lows = quote_arr.get("low") or []
        records: list[tuple[date, float | None, float | None]] = []
        for i, ts in enumerate(timestamps):
            d = datetime.fromtimestamp(int(ts), tz=JST).date()
            if d < WINDOWS["2y"] or d > ANCHOR:
                continue
            close = closes[i] if i < len(closes) else None
            low = lows[i] if i < len(lows) else None
            close_f = float(close) if isinstance(close, (int, float)) else None
            low_f = float(low) if isinstance(low, (int, float)) else None
            records.append((d, close_f, low_f))
        records.sort(key=lambda r: r[0])
        if not records:
            raise RuntimeError("no daily records in requested interval")

        out["first_date"] = records[0][0].isoformat()
        out["last_date"] = records[-1][0].isoformat()
        out["row_count"] = str(len(records))

        anchor_rows = [r for r in records if r[0] == ANCHOR and r[1] is not None]
        if anchor_rows:
            out["close_2026_08_14"] = fmt_num(anchor_rows[-1][1])

        for key, start in WINDOWS.items():
            candidates = [(d, low) for d, _close, low in records if d >= start and d <= ANCHOR and low is not None]
            if candidates:
                min_date, min_low = min(candidates, key=lambda x: (x[1], x[0]))
                out[f"low_{key}"] = fmt_num(min_low)
                out[f"low_{key}_date"] = min_date.isoformat()

        split_events = result.get("events", {}).get("splits", {}) or {}
        split_parts: list[str] = []
        for _k, event in sorted(split_events.items(), key=lambda kv: int(kv[0])):
            ts = event.get("date")
            d = datetime.fromtimestamp(int(ts), tz=JST).date().isoformat() if ts else ""
            ratio = event.get("splitRatio") or ""
            split_parts.append(f"{d}:{ratio}")
        out["split_events"] = "|".join(split_parts)

        missing = [
            k
            for k in ("close_2026_08_14", "low_6m", "low_1y", "low_18m", "low_2y")
            if not out[k]
        ]
        if missing:
            out["status"] = "partial"
            out["error"] = "missing:" + ",".join(missing)
        elif records[0][0] > WINDOWS["2y"]:
            out["status"] = "ok_short_history"
        else:
            out["status"] = "ok"
    except Exception as exc:
        out["status"] = "error"
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out

def main() -> None:
    codes = [
        line.strip()
        for line in Path("stock_job/codes.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fieldnames = [
        "code", "symbol", "close_2026_08_14",
        "low_6m", "low_6m_date",
        "low_1y", "low_1y_date",
        "low_18m", "low_18m_date",
        "low_2y", "low_2y_date",
        "first_date", "last_date", "row_count",
        "split_events", "status", "error",
    ]
    output = Path("stock_job/output")
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "stock_summary_20260814.csv"
    json_path = output / "stock_summary_20260814.json"

    rows: list[dict[str, str]] = []
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, code in enumerate(codes, 1):
            row = summarize(code)
            rows.append(row)
            writer.writerow(row)
            f.flush()
            print(
                f"[{idx:03d}/{len(codes):03d}] {code} {row['status']} "
                f"close={row['close_2026_08_14']} low2y={row['low_2y']} "
                f"{row['error']}",
                flush=True,
            )
            time.sleep(0.18 + random.random() * 0.10)

    json_path.write_text(
        json.dumps(
            {
                "anchor_date": ANCHOR.isoformat(),
                "low_definition": "minimum daily Low, inclusive calendar windows",
                "source": "Yahoo Finance v8 chart endpoint",
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    errors = sum(r["status"] == "error" for r in rows)
    partial = sum(r["status"] == "partial" for r in rows)
    print(f"completed={len(rows)} errors={errors} partial={partial}", flush=True)
    if errors > 30:
        raise SystemExit(f"too many complete failures: {errors}")

if __name__ == "__main__":
    main()
