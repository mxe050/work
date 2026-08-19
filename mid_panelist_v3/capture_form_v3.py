from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, sync_playwright

FORM_URL = "https://forms.gle/6wD16fgubkJrzKym8"


def clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def settle(page: Page, ms: int = 1800) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def safe_text(locator: Locator) -> str:
    try:
        return clean(locator.inner_text(timeout=5_000))
    except Exception:
        return ""


def safe_attr(locator: Locator, name: str) -> str:
    try:
        return locator.get_attribute(name) or ""
    except Exception:
        return ""


def extract_questions(page: Page) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    blocks = page.locator('[role="listitem"]')
    for block_index in range(blocks.count()):
        block = blocks.nth(block_index)
        try:
            if not block.is_visible():
                continue
        except Exception:
            pass

        radios_data: list[dict[str, Any]] = []
        radios = block.locator('[role="radio"]')
        for i in range(radios.count()):
            radio = radios.nth(i)
            radios_data.append({
                "index": i,
                "text": clean(
                    safe_attr(radio, "data-value")
                    or safe_attr(radio, "aria-label")
                    or safe_text(radio)
                ),
                "checked": safe_attr(radio, "aria-checked"),
            })

        checkbox_data: list[dict[str, Any]] = []
        checkboxes = block.locator('[role="checkbox"]')
        for i in range(checkboxes.count()):
            checkbox = checkboxes.nth(i)
            checkbox_data.append({
                "index": i,
                "text": clean(
                    safe_attr(checkbox, "data-answer-value")
                    or safe_attr(checkbox, "aria-label")
                    or safe_text(checkbox)
                ),
                "checked": safe_attr(checkbox, "aria-checked"),
            })

        inputs_data: list[dict[str, Any]] = []
        inputs = block.locator("input, textarea")
        for i in range(inputs.count()):
            input_locator = inputs.nth(i)
            try:
                tag = input_locator.evaluate("el => el.tagName.toLowerCase()")
            except Exception:
                tag = "input"
            try:
                value = input_locator.input_value()
            except Exception:
                value = ""
            inputs_data.append({
                "index": i,
                "type": safe_attr(input_locator, "type") or tag,
                "aria": safe_attr(input_locator, "aria-label"),
                "placeholder": safe_attr(input_locator, "placeholder"),
                "value": value,
            })

        text = safe_text(block)
        if text or radios_data or checkbox_data or inputs_data:
            questions.append({
                "index": block_index,
                "text": text,
                "radios": radios_data,
                "checkboxes": checkbox_data,
                "inputs": inputs_data,
            })
    return questions


def click_first_enabled(locator: Locator) -> bool:
    for i in range(locator.count()):
        item = locator.nth(i)
        try:
            if item.is_visible() and item.get_attribute("aria-disabled") != "true":
                item.click(force=True)
                return True
        except Exception:
            continue
    return False


def fill_current_page(page: Page) -> dict[str, int]:
    stats = {
        "email": 0,
        "text": 0,
        "number": 0,
        "textarea": 0,
        "radio_groups": 0,
        "checkbox_blocks": 0,
        "dropdowns": 0,
    }

    for loc in page.locator('input[type="email"]').all():
        try:
            if loc.is_visible() and loc.is_editable() and not loc.input_value():
                loc.fill("practice@example.com")
                stats["email"] += 1
        except Exception:
            pass

    for loc in page.locator('input[type="text"]').all():
        try:
            if loc.is_visible() and loc.is_editable() and not loc.input_value():
                label = " ".join(filter(None, [loc.get_attribute("aria-label"), loc.get_attribute("placeholder")]))
                value = "練習回答"
                if "メール" in label or "email" in label.lower():
                    value = "practice@example.com"
                loc.fill(value)
                stats["text"] += 1
        except Exception:
            pass

    for loc in page.locator('input[type="number"]').all():
        try:
            if loc.is_visible() and loc.is_editable() and not loc.input_value():
                loc.fill("1")
                stats["number"] += 1
        except Exception:
            pass

    for loc in page.locator("textarea").all():
        try:
            if loc.is_visible() and loc.is_editable() and not loc.input_value():
                loc.fill("練習回答")
                stats["textarea"] += 1
        except Exception:
            pass

    groups = page.locator('[role="radiogroup"]')
    for i in range(groups.count()):
        group = groups.nth(i)
        try:
            if not group.is_visible():
                continue
            radios = group.locator('[role="radio"]')
            selected = any(radios.nth(j).get_attribute("aria-checked") == "true" for j in range(radios.count()))
            if not selected and click_first_enabled(radios):
                stats["radio_groups"] += 1
        except Exception:
            pass

    seen_names: set[str] = set()
    radios = page.locator('input[type="radio"]')
    for i in range(radios.count()):
        radio = radios.nth(i)
        try:
            if not radio.is_visible():
                continue
            name = radio.get_attribute("name") or f"unnamed-{i}"
            if name in seen_names:
                continue
            seen_names.add(name)
            if not radio.is_checked():
                radio.check(force=True)
                stats["radio_groups"] += 1
        except Exception:
            pass

    blocks = page.locator('[role="listitem"]')
    for i in range(blocks.count()):
        block = blocks.nth(i)
        try:
            if not block.is_visible():
                continue
            checks = block.locator('[role="checkbox"]')
            if checks.count() == 0:
                continue
            any_checked = any(checks.nth(j).get_attribute("aria-checked") == "true" for j in range(checks.count()))
            if not any_checked and click_first_enabled(checks):
                stats["checkbox_blocks"] += 1
        except Exception:
            pass

    dropdowns = page.locator('[role="listbox"]')
    for i in range(dropdowns.count()):
        dropdown = dropdowns.nth(i)
        try:
            if not dropdown.is_visible():
                continue
            dropdown.click(force=True)
            page.wait_for_timeout(300)
            options = page.locator('[role="option"]')
            if click_first_enabled(options):
                stats["dropdowns"] += 1
        except Exception:
            pass

    return stats


def find_button(page: Page, labels: list[str]) -> Locator | None:
    for label in labels:
        candidates = [
            page.get_by_role("button", name=label, exact=True),
            page.locator('div[role="button"]').filter(has_text=label),
            page.locator("button").filter(has_text=label),
        ]
        for candidate in candidates:
            try:
                if candidate.count() and candidate.first.is_visible():
                    return candidate.first
            except Exception:
                pass
    return None


def has_submit(page: Page) -> bool:
    return find_button(page, ["送信", "Submit"]) is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=25)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    browser_exec = os.environ.get("BROWSER_EXECUTABLE") or None
    report: dict[str, Any] = {"source_url": FORM_URL, "pages": []}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=browser_exec,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=ja-JP"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ja-JP",
            color_scheme="light",
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=90_000)
        settle(page, 2500)
        report["resolved_url"] = page.url
        report["title"] = page.title()
        seen: set[str] = set()

        for page_number in range(1, args.max_pages + 1):
            settle(page, 1000)
            body = clean(page.locator("body").inner_text(timeout=30_000))
            signature = body[:1800]
            if signature in seen:
                report["loop_detected_at"] = page_number
                break
            seen.add(signature)

            stem = f"form_page_{page_number:02d}"
            screenshot_path = out / f"{stem}.png"
            text_path = out / f"{stem}.txt"
            json_path = out / f"{stem}.json"
            page.screenshot(path=str(screenshot_path), full_page=True)
            text_path.write_text(body, encoding="utf-8")
            questions = extract_questions(page)
            entry: dict[str, Any] = {
                "page_number": page_number,
                "url": page.url,
                "title": page.title(),
                "body_text": body,
                "questions": questions,
                "has_submit": has_submit(page),
                "screenshot": screenshot_path.name,
            }
            report["pages"].append(entry)
            json_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

            if entry["has_submit"]:
                break

            entry["navigation_fill_stats"] = fill_current_page(page)
            next_button = find_button(page, ["次へ", "Next"])
            if next_button is None:
                entry["navigation_error"] = "Next button not found"
                break
            next_button.scroll_into_view_if_needed()
            next_button.click(force=True)
            settle(page, 1800)

        browser.close()

    (out / "form_audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary: list[str] = []
    for entry in report["pages"]:
        summary.append(f"===== PAGE {entry['page_number']} =====")
        summary.append(entry["body_text"])
        summary.append("")
    (out / "form_all_pages.txt").write_text("\n".join(summary), encoding="utf-8")
    print(json.dumps({
        "resolved_url": report.get("resolved_url"),
        "title": report.get("title"),
        "pages": len(report["pages"]),
        "final_has_submit": bool(report["pages"] and report["pages"][-1].get("has_submit")),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
