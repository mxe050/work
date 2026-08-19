from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

MIDCHECK_URL = "https://core-grade-guide-1-mxe050s-projects.vercel.app/mid-grade-two-flows/midcheck.html"
MANUAL_URL = "https://core-grade-guide-1-mxe050s-projects.vercel.app/#midg-guyatt-manual"
DETAIL_URL = "https://core-grade-guide-1-mxe050s-projects.vercel.app/guyatt-zeng-panel-survey/index.html#gzs-start"
YOUTUBE_URL = "https://www.youtube.com/watch?v=9oLoRjUXwJg"
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfP0e9E3BztJhK6TQgT8ig9eJXbFRILQyt_MF550ySLGoiD9w/viewform"


def clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def goto(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(3_000)


def save_page(page: Page, out: Path, stem: str, full_page: bool = True) -> dict[str, Any]:
    text = clean(page.locator("body").inner_text(timeout=30_000))
    (out / f"{stem}.txt").write_text(text, encoding="utf-8")
    page.screenshot(path=str(out / f"{stem}.png"), full_page=full_page)
    return {
        "stem": stem,
        "title": page.title(),
        "url": page.url,
        "text_chars": len(text),
        "screenshot": f"{stem}.png",
        "text_file": f"{stem}.txt",
    }


def question_blocks(page: Page) -> list[dict[str, Any]]:
    script = r"""
    () => {
      const blocks = Array.from(document.querySelectorAll('[role="listitem"]'));
      return blocks.map((block, index) => {
        const text = (block.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
        const radios = Array.from(block.querySelectorAll('[role="radio"]')).map(x => ({
          text: (x.getAttribute('data-value') || x.getAttribute('aria-label') || x.innerText || '').trim(),
          checked: x.getAttribute('aria-checked')
        }));
        const checks = Array.from(block.querySelectorAll('[role="checkbox"]')).map(x => ({
          text: (x.getAttribute('data-answer-value') || x.getAttribute('aria-label') || x.innerText || '').trim(),
          checked: x.getAttribute('aria-checked')
        }));
        const inputs = Array.from(block.querySelectorAll('input, textarea')).map(x => ({
          type: x.getAttribute('type') || x.tagName.toLowerCase(),
          aria: x.getAttribute('aria-label') || '',
          placeholder: x.getAttribute('placeholder') || ''
        }));
        return {index, text, radios, checks, inputs};
      }).filter(x => x.text || x.radios.length || x.checks.length || x.inputs.length);
    }
    """
    return page.evaluate(script)


def fill_current_form_page(page: Page) -> None:
    for locator in page.locator("input[type='email']").all():
        if locator.is_visible():
            locator.fill("panelist@example.com")
    for locator in page.locator("input[type='text']").all():
        if locator.is_visible() and not locator.input_value():
            locator.fill("練習回答")
    for locator in page.locator("input[type='number']").all():
        if locator.is_visible() and not locator.input_value():
            locator.fill("1")
    for locator in page.locator("textarea").all():
        if locator.is_visible() and not locator.input_value():
            locator.fill("練習回答")

    for group in page.locator("div[role='radiogroup']").all():
        if not group.is_visible():
            continue
        radios = group.locator("div[role='radio']")
        for i in range(radios.count()):
            radio = radios.nth(i)
            if radio.is_visible() and radio.get_attribute("aria-disabled") != "true":
                if radio.get_attribute("aria-checked") != "true":
                    radio.click(force=True)
                break

    for block in page.locator("div[role='listitem']").all():
        if not block.is_visible():
            continue
        checks = block.locator("div[role='checkbox']")
        if checks.count() and not any(checks.nth(i).get_attribute("aria-checked") == "true" for i in range(checks.count())):
            for i in range(checks.count()):
                check = checks.nth(i)
                if check.is_visible() and check.get_attribute("aria-disabled") != "true":
                    check.click(force=True)
                    break


def find_next_button(page: Page):
    candidates = [
        page.get_by_role("button", name=re.compile(r"^(次へ|Next)$")),
        page.locator("div[role='button']").filter(has_text=re.compile(r"^(次へ|Next)$")),
    ]
    for candidate in candidates:
        if candidate.count() and candidate.first.is_visible():
            return candidate.first
    return None


def has_submit_button(page: Page) -> bool:
    texts = page.locator("div[role='button'], button").all_inner_texts()
    return any(clean(t) in {"送信", "Submit"} for t in texts)


def audit_form(page: Page, out: Path) -> list[dict[str, Any]]:
    goto(page, FORM_URL)
    pages: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()

    for page_no in range(1, 16):
        page.wait_for_timeout(1_500)
        body_text = clean(page.locator("body").inner_text(timeout=30_000))
        signature = body_text[:1000]
        if signature in seen_signatures:
            raise RuntimeError(f"Form navigation loop detected at page {page_no}")
        seen_signatures.add(signature)

        stem = f"form_page_{page_no:02d}"
        page.screenshot(path=str(out / f"{stem}.png"), full_page=True)
        (out / f"{stem}.txt").write_text(body_text, encoding="utf-8")
        blocks = question_blocks(page)
        record = {
            "page_number": page_no,
            "title": page.title(),
            "url": page.url,
            "body_text": body_text,
            "questions": blocks,
            "has_submit": has_submit_button(page),
            "screenshot": f"{stem}.png",
        }
        pages.append(record)
        (out / f"{stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        if record["has_submit"]:
            break

        fill_current_form_page(page)
        next_button = find_next_button(page)
        if next_button is None:
            raise RuntimeError(f"No Next button found on form page {page_no}")
        next_button.click(force=True)
        page.wait_for_timeout(2_000)

    (out / "form_all_pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_lines: list[str] = []
    for entry in pages:
        summary_lines.append(f"===== FORM PAGE {entry['page_number']} =====")
        summary_lines.append(entry["body_text"])
        summary_lines.append("")
    (out / "form_all_pages.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"static_pages": [], "form_pages": []}
    with sync_playwright() as p:
        executable = os.environ.get("BROWSER_EXECUTABLE")
        browser = p.chromium.launch(
            headless=True,
            executable_path=executable if executable else None,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=ja-JP"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=1,
            locale="ja-JP",
            color_scheme="light",
        )
        page = context.new_page()

        for stem, url in [
            ("midcheck_full", MIDCHECK_URL),
            ("manual_full", MANUAL_URL),
            ("detail_full", DETAIL_URL),
            ("youtube_reference", YOUTUBE_URL),
        ]:
            goto(page, url)
            report["static_pages"].append(save_page(page, out, stem, full_page=True))

        report["form_pages"] = audit_form(page, out)
        browser.close()

    (out / "audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "static_pages": len(report["static_pages"]),
        "form_pages": len(report["form_pages"]),
        "output": str(out),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
