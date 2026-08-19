#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import async_playwright, Page, Locator

MANUAL_URL = "https://core-grade-guide-1-mxe050s-projects.vercel.app/#midg-guyatt-manual"
DETAIL_URL = "https://core-grade-guide-1-mxe050s-projects.vercel.app/guyatt-zeng-panel-survey/index.html#gzs-start"
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfP0e9E3BztJhK6TQgT8ig9eJXbFRILQyt_MF550ySLGoiD9w/viewform"
YOUTUBE_ID = "9oLoRjUXwJg"


def safe_name(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^0-9A-Za-z_\-]+", "", text)
    return text[:80] or "capture"


async def settle(page: Page, ms: int = 1800) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    await page.wait_for_timeout(ms)


async def save_page(page: Page, out: Path, stem: str, full_page: bool = True) -> dict[str, Any]:
    text = await page.locator("body").inner_text(timeout=20000)
    (out / f"{stem}.txt").write_text(text, encoding="utf-8")
    await page.screenshot(path=str(out / f"{stem}.png"), full_page=full_page)
    return {
        "stem": stem,
        "url": page.url,
        "title": await page.title(),
        "text_length": len(text),
    }


async def click_text_if_present(page: Page, patterns: list[str]) -> list[str]:
    clicked: list[str] = []
    for pattern in patterns:
        loc = page.get_by_text(pattern, exact=False)
        count = await loc.count()
        for i in range(min(count, 4)):
            item = loc.nth(i)
            try:
                if await item.is_visible():
                    await item.scroll_into_view_if_needed()
                    await item.click(timeout=2500)
                    clicked.append(pattern)
                    await page.wait_for_timeout(700)
                    break
            except Exception:
                continue
    return clicked


async def screenshot_text_container(page: Page, phrase: str, path: Path, max_height: int = 2100) -> dict[str, Any]:
    result = await page.evaluate(
        """
        ({phrase, maxHeight}) => {
          const all = Array.from(document.querySelectorAll('body *'));
          const candidates = all.filter(el => {
            const t = (el.innerText || '').trim();
            return t && t.includes(phrase);
          }).sort((a,b) => (a.innerText || '').length - (b.innerText || '').length);
          if (!candidates.length) return null;
          let el = candidates[0];
          let best = el;
          for (let i=0; i<8 && el; i++, el=el.parentElement) {
            const r = el.getBoundingClientRect();
            const text = (el.innerText || '').trim();
            if (r.width >= 650 && r.height >= 160 && r.height <= maxHeight && text.length <= 9000) best = el;
          }
          best.setAttribute('data-oai-capture-target', '1');
          const r = best.getBoundingClientRect();
          return {tag: best.tagName, text: (best.innerText || '').slice(0,1200), rect: {x:r.x,y:r.y,width:r.width,height:r.height}};
        }
        """,
        {"phrase": phrase, "maxHeight": max_height},
    )
    if not result:
        return {"phrase": phrase, "found": False}
    loc = page.locator('[data-oai-capture-target="1"]').last
    await loc.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)
    await loc.screenshot(path=str(path))
    await page.evaluate("document.querySelectorAll('[data-oai-capture-target]').forEach(el=>el.removeAttribute('data-oai-capture-target'))")
    return {"phrase": phrase, "found": True, **result}


async def capture_manual(page: Page, out: Path) -> dict[str, Any]:
    await page.goto(MANUAL_URL, wait_until="domcontentloaded", timeout=90000)
    await settle(page)
    clicked = await click_text_if_present(page, [
        "0．結論を先に：違いは二点",
        "本文",
        "MIDをパネル会議で決定するための２つの方法",
        "MIDをパネル会議で決定するための2つの方法",
    ])
    full = await save_page(page, out, "manual_full")
    phrases = {
        "mid_mic_figure": "図：MIDは群間差、MICは患者内変化として区別して読む",
        "two_methods": "MIDをパネル会議で決定するための２つの方法",
        "two_differences": "違いは二点",
        "guyatt": "Guyatt",
    }
    sections = {}
    for stem, phrase in phrases.items():
        sections[stem] = await screenshot_text_container(page, phrase, out / f"manual_{stem}.png")
    return {"page": full, "clicked": clicked, "sections": sections}


async def capture_detail(page: Page, out: Path) -> dict[str, Any]:
    await page.goto(DETAIL_URL, wait_until="domcontentloaded", timeout=90000)
    await settle(page)
    full = await save_page(page, out, "detail_full")
    phrases = {
        "two_judgments": "最初に行う二つの判断",
        "panel_role": "回答するのはパネル委員です",
        "objective1": "Objective 1",
        "turning_point": "重要／些細の境界",
    }
    sections = {}
    for stem, phrase in phrases.items():
        sections[stem] = await screenshot_text_container(page, phrase, out / f"detail_{stem}.png")
    return {"page": full, "sections": sections}


async def fill_visible_controls(page: Page) -> dict[str, int]:
    stats = {"text": 0, "radio": 0, "checkbox": 0}
    # Text/email fields.
    for selector, value in [
        ('input[type="email"]', 'practice@example.com'),
        ('input[type="text"]', '練習回答'),
        ('textarea', '練習回答'),
    ]:
        loc = page.locator(selector)
        for i in range(await loc.count()):
            item = loc.nth(i)
            try:
                if await item.is_visible() and await item.is_editable():
                    current = await item.input_value()
                    if not current:
                        label = (await item.get_attribute("aria-label") or "") + " " + (await item.get_attribute("name") or "")
                        use = 'practice@example.com' if ('メール' in label or 'email' in label.lower()) else value
                        await item.fill(use)
                        stats["text"] += 1
            except Exception:
                pass
    # One choice per radiogroup, including grid rows.
    groups = page.locator('[role="radiogroup"]')
    for gi in range(await groups.count()):
        group = groups.nth(gi)
        radios = group.locator('[role="radio"]')
        for ri in range(await radios.count()):
            radio = radios.nth(ri)
            try:
                if await radio.is_visible() and (await radio.get_attribute('aria-checked')) != 'true':
                    await radio.click()
                    stats["radio"] += 1
                    break
            except Exception:
                continue
    # Fallback radio inputs not wrapped in radiogroup.
    radios = page.locator('input[type="radio"]')
    named: set[str] = set()
    for i in range(await radios.count()):
        radio = radios.nth(i)
        try:
            if not await radio.is_visible():
                continue
            name = await radio.get_attribute('name') or f'unnamed-{i}'
            if name in named:
                continue
            named.add(name)
            if not await radio.is_checked():
                await radio.check(force=True)
                stats["radio"] += 1
        except Exception:
            pass
    # Select first visible checkbox only when none selected in its question block.
    blocks = page.locator('div[role="listitem"]')
    for bi in range(await blocks.count()):
        block = blocks.nth(bi)
        checks = block.locator('[role="checkbox"], input[type="checkbox"]')
        if await checks.count() == 0:
            continue
        any_checked = False
        for ci in range(await checks.count()):
            c = checks.nth(ci)
            try:
                state = await c.get_attribute('aria-checked')
                if state == 'true' or (await c.get_attribute('type')) == 'checkbox' and await c.is_checked():
                    any_checked = True
            except Exception:
                pass
        if any_checked:
            continue
        for ci in range(await checks.count()):
            c = checks.nth(ci)
            try:
                if await c.is_visible():
                    await c.click(force=True)
                    stats["checkbox"] += 1
                    break
            except Exception:
                continue
    return stats


async def find_action_button(page: Page, labels: list[str]) -> Locator | None:
    for label in labels:
        for selector in [f'[role="button"]:has-text("{label}")', f'button:has-text("{label}")', f'text="{label}"']:
            loc = page.locator(selector)
            for i in range(await loc.count()):
                item = loc.nth(i)
                try:
                    if await item.is_visible():
                        return item
                except Exception:
                    pass
    return None


async def capture_form(page: Page, out: Path) -> dict[str, Any]:
    await page.goto(FORM_URL, wait_until="domcontentloaded", timeout=90000)
    await settle(page, 2500)
    pages: list[dict[str, Any]] = []
    for index in range(1, 16):
        stem = f"form_page_{index:02d}"
        text = await page.locator('body').inner_text(timeout=20000)
        (out / f"{stem}.txt").write_text(text, encoding='utf-8')
        await page.screenshot(path=str(out / f"{stem}.png"), full_page=True)
        record: dict[str, Any] = {
            "index": index,
            "url": page.url,
            "text_length": len(text),
            "preview": text[:1200],
        }
        submit = await find_action_button(page, ["送信", "Submit"])
        nxt = await find_action_button(page, ["次へ", "Next"])
        if submit is not None and nxt is None:
            record["final_page"] = True
            pages.append(record)
            break
        fill_stats = await fill_visible_controls(page)
        record["filled"] = fill_stats
        nxt = await find_action_button(page, ["次へ", "Next"])
        if nxt is None:
            record["stopped"] = "No Next button"
            pages.append(record)
            break
        try:
            await nxt.scroll_into_view_if_needed()
            await nxt.click(timeout=6000)
            await settle(page, 1200)
            record["advanced"] = True
        except Exception as exc:
            record["advanced"] = False
            record["error"] = repr(exc)
            pages.append(record)
            break
        pages.append(record)
    return {"pages": pages, "count": len(pages)}


async def main_async(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"urls": {"manual": MANUAL_URL, "detail": DETAIL_URL, "form": FORM_URL}}
    browser_exec = os.environ.get("BROWSER_EXECUTABLE") or None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=browser_exec,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=ja-JP"],
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ja-JP", device_scale_factor=1)
        page = await context.new_page()
        report["manual"] = await capture_manual(page, output)
        report["detail"] = await capture_detail(page, output)
        report["form"] = await capture_form(page, output)
        await browser.close()
    thumb_url = f"https://i.ytimg.com/vi/{YOUTUBE_ID}/hqdefault.jpg"
    try:
        r = requests.get(thumb_url, timeout=30)
        r.raise_for_status()
        (output / "youtube_thumbnail.jpg").write_bytes(r.content)
        report["youtube_thumbnail"] = {"url": thumb_url, "bytes": len(r.content)}
    except Exception as exc:
        report["youtube_thumbnail"] = {"url": thumb_url, "error": repr(exc)}
    (output / "capture_report_v2.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/captures_v2"))
    args = parser.parse_args()
    asyncio.run(main_async(args.output))


if __name__ == "__main__":
    main()
