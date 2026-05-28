import asyncio
from playwright.async_api import async_playwright
import os
import subprocess
import time

async def verify_ui_v5():
    # Start the app using uvicorn
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{os.getcwd()}/src"
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "hl_observer.ui.app:create_ui_app", "--factory", "--host", "127.0.0.1", "--port", "5001"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    time.sleep(5) # Give server time to start

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1280, 'height': 1200})

        try:
            await page.goto("http://127.0.0.1:5001")

            # 1. Verify and capture Simple Dashboard
            await page.wait_for_selector("#mainDashboard")
            await page.screenshot(path="dashboard_v5_simple.png")
            print("Captured dashboard_v5_simple.png")

            # 2. Check for the new stats bar elements
            wr = await page.inner_text("#statWinRate")
            print(f"Verified Win Rate visible: {wr}")

            # 3. Toggle Expert Mode
            await page.click("#expertToggle")
            await page.wait_for_selector("#expertView:not(.hidden)")
            await page.screenshot(path="dashboard_v5_expert.png")
            print("Captured dashboard_v5_expert.png")

        except Exception as e:
            print(f"Error during verification: {e}")
        finally:
            await browser.close()
            proc.terminate()

if __name__ == "__main__":
    asyncio.run(verify_ui_v5())
