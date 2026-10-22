#!/usr/bin/env python3
"""site_shots.py — the README's pictures of the explorer site (docs/images/explorer/site-*.png).

    python3 docs/tools/site_shots.py            after python3 docs/tools/build_site.py

Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora. It opens the built
pages in headless Chromium and photographs three parts of them:

    site-hero.jpg       the overview's opening shot, early in its scroll
    site-deadline.png   the overview's "fire a deadline" lab, light theme
    site-zoom.png       the die zoom on its last view, one flip-flop
    site-tours.png      the tour player and its waveform, dark theme

The pages are what they show: nothing is staged. Reduced motion is on, so every
picture is a still frame of the page's own end state, except the opening shot, which
is scrolled a little way in and left to settle. Unlike the other generated
images these are not byte-for-byte reproducible (font rasterising differs between
Chromium builds), so make docs does not compare them; rerun this after changing
the site. Needs Playwright for Python (pip install playwright) and a Chromium;
set CHROMIUM=/path/to/chrome to use one that is already installed.
"""
import asyncio, os, pathlib

SITE = pathlib.Path("docs/site").resolve()
OUT = "docs/images/explorer"


async def main():
    from playwright.async_api import async_playwright
    exe = os.environ.get("CHROMIUM")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"] if exe else [])

        async def shoot(page_id, scheme, selector, name, before=None, upto=None, motion="reduce"):
            ctx = await b.new_context(viewport={"width": 1200, "height": 800}, color_scheme=scheme,
                                      reduced_motion=motion, device_scale_factor=1)
            page = await ctx.new_page()
            await page.goto((SITE / f"{page_id}.html").as_uri())
            await page.add_style_tag(content=".top { position: static !important; }")  # keep the header out of the picture
            el = page.locator(selector)
            await el.scroll_into_view_if_needed()
            if before:
                await before(page)
            await page.wait_for_timeout(300)
            if upto:   # from the top of selector down to the bottom of upto
                a, z = await el.bounding_box(), await page.locator(upto).first.bounding_box()
                sy = await page.evaluate("scrollY")   # boxes are in the viewport; a full-page clip is in the page
                await page.screenshot(path=f"{OUT}/{name}", full_page=True,
                                      clip={"x": a["x"], "y": a["y"] + sy, "width": a["width"], "height": z["y"] + z["height"] - a["y"]})
            else:
                await el.screenshot(path=f"{OUT}/{name}", **({"quality": 82} if name.endswith(".jpg") else {}))
            await ctx.close()
            print(f"wrote {OUT}/{name} ({os.path.getsize(f'{OUT}/{name}') / 1024:.0f} KB)")

        async def last_view(page):
            await page.locator(".zoom-go button").nth(3).click()

        async def early(page):
            await page.evaluate("scrollTo({top: (document.getElementById('reveal').offsetHeight - innerHeight) * .12, behavior: 'instant'})")
            await page.wait_for_timeout(1500)

        await shoot("index", "dark", ".reveal-stage", "site-hero.jpg", early, motion="no-preference")
        await shoot("index", "light", "#deadline", "site-deadline.png")
        await shoot("index", "dark", ".zoom-stage", "site-zoom.png", last_view)
        await shoot("tours", "dark", "#player .player", "site-tours.png", upto="#player .wave")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
