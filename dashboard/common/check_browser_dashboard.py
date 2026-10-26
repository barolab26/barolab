import asyncio
from playwright.async_api import async_playwright

async def inspect_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"FAILED: {req.url} -> {req.failure}"))
        page.on("response", lambda res: failed_requests.append(f"STATUS {res.status}: {res.url}") if res.status >= 400 else None)
        
        await page.goto("http://127.0.0.1:8790/", wait_until="networkidle")
        await asyncio.sleep(2)
        
        print("\n=== Failed Requests ===")
        for r in failed_requests:
            print(" ", r)
            
        await browser.close()

asyncio.run(inspect_dashboard())
