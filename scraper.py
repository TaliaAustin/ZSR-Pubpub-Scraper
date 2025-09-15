import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # For development, you might set headless=False to see the browser window
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to https://urbanafrica.pubpub.org/")
        await page.goto("https://urbanafrica.pubpub.org/")
        print(f"Current page title: {await page.title()}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main()) 