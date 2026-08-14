"""
Sample Playwright Edge launcher (async). Use this as a template to start a persistent Edge context
that preserves cookies/session via user_data_dir.
"""
import asyncio
import os
from playwright.async_api import async_playwright
from config import Config


async def launch_edge():
    playwright = await async_playwright().start()
    launch_args = Config.PLAYWRIGHT_LAUNCH_ARGS.split()
    # If EDGE_EXECUTABLE_PATH set, pass it to channel via executablePath in chromium.launch_persistent_context
    user_data_dir = Config.EDGE_USER_DATA_DIR

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        channel=Config.PLAYWRIGHT_CHANNEL,
        headless=Config.HEADLESS_MODE,
        args=launch_args,
        executable_path=Config.EDGE_EXECUTABLE_PATH or None,
    )

    page = await context.new_page()
    # Example: anti-detection tweaks (use responsibly)
    await page.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}) }")

    await page.goto("https://example.com")
    print("Page title:", await page.title())

    # keep running until manual stop
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        await context.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(launch_edge())
