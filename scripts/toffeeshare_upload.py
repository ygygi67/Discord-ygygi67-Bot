
import asyncio
from playwright.async_api import async_playwright
import sys
import os

async def run(filepath):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://toffeeshare.com/")
        
        # Wait for the file input
        # Note: ToffeeShare might use a hidden input or a button that opens a dialog
        # Usually it's an input[type='file']
        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(filepath)
        
        print("File selected, waiting for link...")
        sys.stdout.flush()
        
        # Wait for the link to appear
        # We search for any input that contains 'toffeeshare.com/'
        max_retries = 30
        link = None
        for _ in range(max_retries):
            link = await page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll('input'));
                const linkInput = inputs.find(i => i.value.includes('toffeeshare.com/'));
                return linkInput ? linkInput.value : null;
            }""")
            if link:
                break
            await asyncio.sleep(1)
            
        if link:
            print(f"LINK:{link}")
            sys.stdout.flush()
            # Keep alive for 60 minutes or until killed
            # We also need to keep the browser running
            await asyncio.sleep(3600) 
        else:
            print("ERROR: Could not find share link")
            sys.stdout.flush()
            
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    # Check if file exists
    if not os.path.exists(sys.argv[1]):
        print(f"ERROR: File not found: {sys.argv[1]}")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
