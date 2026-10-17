"""Capture README screenshots of a running dashboard.

pip install playwright            # plus `playwright install chromium` if no Edge/Chrome
streamlit run dashboard/app.py --server.port 8517
python scripts/capture_screenshots.py --url http://localhost:8517
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

# name -> (url path, viewport height). Streamlit scrolls an inner container, so a tall
# viewport is used instead of Playwright's full-page mode.
PAGES = {
    "overview": ("", 2350),
    "population_trends": ("population-trends", 1500),
    "demographics": ("demographics", 1900),
    "comparison": ("comparison", 1700),
    "data_explorer": ("explorer", 1250),
    "pipeline_health": ("pipeline-health", 1750),
}
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8517")
    parser.add_argument("--channel", default="msedge", help="msedge, chrome or '' for bundled")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--only", nargs="*", help="Subset of page names")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel or None)
        page = browser.new_page(
            viewport={"width": args.width, "height": 1000}, device_scale_factor=1.25
        )
        for name, (path, height) in PAGES.items():
            if args.only and name not in args.only:
                continue
            page.set_viewport_size({"width": args.width, "height": height})
            page.goto(f"{args.url}/{path}", wait_until="networkidle")
            page.wait_for_selector('[data-testid="stAppViewContainer"]')
            page.wait_for_function(
                "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=60000
            )
            page.wait_for_timeout(2500)  # let Plotly finish its first paint
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target))
            print(f"saved {target}")
        browser.close()


if __name__ == "__main__":
    main()
