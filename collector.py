"""Read permitted public page, NEVER click a voting button or bypass access controls.
All DOM selectors are intentionally supplied by the operator after page inspection.
"""
import hashlib
import os
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from score_parser import parse_score
from storage import insert_snapshots

load_dotenv()

def get_text(card, selector):
    el = card.locator(selector).first
    if el.count() == 0:
        raise ValueError(f"Missing element for selector {selector}")
    return el.inner_text().strip()


def run():
    required = ["VOTING_URL", "CARD_SELECTOR", "NAME_SELECTOR", "SCORE_SELECTOR"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing settings: " + ", ".join(missing) + ". Inspect page before configuring selectors.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="zh-CN", timezone_id="Asia/Shanghai")
            page.goto(os.environ["VOTING_URL"], wait_until="domcontentloaded", timeout=40000)
            tab = os.getenv("CATEGORY_TAB_SELECTOR", "").strip()
            if tab:
                # Must be a verified, category-only control (NOT a voting button).
                page.locator(tab).click(timeout=5000)
            cards_selector = os.environ["CARD_SELECTOR"]
            page.locator(cards_selector).first.wait_for(timeout=15000)
            for _ in range(min(int(os.getenv("SCROLL_ROUNDS", "3")), 8)):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(650)

            cards = page.locator(cards_selector)
            count = cards.count()
            if count == 0:
                raise RuntimeError("No candidate cards found; inspect the page or selectors")
            timestamp = datetime.now(timezone.utc).isoformat()
            stage = os.getenv("STAGE", "final")
            records = []
            seen = set()
            for i in range(count):
                card = cards.nth(i)
                name = get_text(card, os.environ["NAME_SELECTOR"])
                raw_score = get_text(card, os.environ["SCORE_SELECTOR"])
                score, approx = parse_score(raw_score)
                id_attribute = os.getenv("ID_ATTRIBUTE", "").strip()
                candidate_id = card.get_attribute(id_attribute) if id_attribute else None
                if not candidate_id:
                    candidate_id = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
                if candidate_id in seen:
                    raise RuntimeError(f"Duplicate candidate ID {candidate_id}; possible duplicated list items")
                seen.add(candidate_id)
                rank_sel = os.getenv("RANK_SELECTOR", "").strip()
                rank = None
                if rank_sel:
                    rank_str = get_text(card, rank_sel)
                    matched = re.search(r"\d+", rank_str)
                    rank = int(matched.group()) if matched else None
                records.append({
                    "stage": stage, "category": "剧综人物",
                    "candidate_id": candidate_id, "candidate_name": name,
                    "score": score, "score_approx": approx, "rank": rank,
                    "observed_at": timestamp, "source": "public_page"
                })
            print(f"Extracted {len(records)} records; approx={sum(r['score_approx'] for r in records)}; URL={page.url}")
        finally:
            browser.close()

    insert_snapshots(records)
    print("Snapshot stored")


if __name__ == "__main__":
    run()
