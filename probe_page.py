"""Manual one-time page inspection. Does not log in, solve CAPTCHAs, or cast votes.
Run ONLY where browser automation is permitted by the page operator.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
url = os.environ.get("VOTING_URL")
if not url:
    raise RuntimeError("Set VOTING_URL")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(locale="zh-CN")
    page.goto(url, wait_until="domcontentloaded", timeout=40000)
    print("Resolved URL:", page.url)
    print("Title:", page.title())
    print("Visible page text (first 2500 chars):")
    print(page.locator("body").inner_text()[:2500])
    Path("debug").mkdir(exist_ok=True)
    page.screenshot(path="debug/page.png", full_page=True)
    print("Screenshot: debug/page.png")
    browser.close()
