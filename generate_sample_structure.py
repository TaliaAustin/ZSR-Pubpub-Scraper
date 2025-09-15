import asyncio
import json
import re
import os
from datetime import datetime
from playwright.async_api import async_playwright

BASE_URL = "https://urbanafrica.pubpub.org/"
OUTPUT_DIR = "sample_ver3" # Your desired output directory name

def slugify(text):
    """
    Generates a URL-friendly slug from a given text.
    """
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text) # Remove non-word chars
    text = re.sub(r'[\s_-]+', '-', text) # Replace spaces/underscores with single dash
    text = re.sub(r'^-+|-+$', '', text) # Remove leading/trailing dashes
    return text

async def discover_top_level_collections():
    print(f"Starting top-level collection discovery for {BASE_URL}")

    global_manifest = {
        "project_name": "PubPub Content Preservation",
        "source_url": BASE_URL,
        "extraction_start_date": datetime.now().isoformat(),
        "extraction_end_date": None, # Will be filled at the end
        "total_collections_found": 0,
        "total_publications_found": 0,
        "total_media_assets_downloaded": 0,
        "collections": []
    }

    async with async_playwright() as p:
        # Launch browser in headful mode for initial debugging if needed (headless=False)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Navigating to {BASE_URL}...")
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        
        # Give some extra time for JavaScript to render.
        # Based on screenshot, content seems to be in initial HTML, but a small wait is safe.
        await page.wait_for_timeout(1000) # Wait 1 second
        await page.screenshot(path="debug_screenshot_homepage.png", full_page=True)
        print("Debug screenshot saved to debug_screenshot_homepage.png")
        print("Page loaded. Attempting to locate collection links using refined selector.")

        # --- REFINED SELECTOR BASED ON YOUR SCREENSHOT ---
        # Target <a> tags with class 'page-preview-component' and an href containing '/collection/'
        # that are direct children of div.col-12
        collection_locator = page.locator("div.col-12 > a.page-preview-component[href*='/collection/']")
        
        # Get all matching elements
        link_elements = await collection_locator.all()
        
        print(f"Found {len(link_elements)} elements matching the refined collection selector.")

        unique_links_data = {} # Use dict to track unique links by URL

        for link_element in link_elements:
            # The title is inside a <span> within the <a> tag
            title_span = await link_element.locator("span").first.text_content()
            url_path = await link_element.get_attribute("href")

            if title_span and url_path and url_path.startswith("/collection/"):
                full_url = BASE_URL.rstrip('/') + url_path
                
                # Check if this URL has already been processed
                if full_url not in unique_links_data:
                    unique_links_data[full_url] = {
                        "title": title_span.strip(), # Use the text from the span
                        "url_path": url_path
                    }
        
        print(f"Identified {len(unique_links_data)} unique top-level collection links.")

        for full_url, data in unique_links_data.items():
            coll_title = data["title"]
            coll_slug = slugify(coll_title)
            
            collection_data = {
                "slug": coll_slug,
                "title": coll_title,
                "url": full_url,
                "publication_count": 0, # Placeholder, will be updated in next phase
                # Use os.path.join for cross-OS path compatibility
                "manifest_path": os.path.join(OUTPUT_DIR, "collections", coll_slug, "collection-manifest.json").replace("\\", "/")
            }
            global_manifest["collections"].append(collection_data)
            print(f"  Discovered Collection: '{coll_title}' ({full_url})")

        global_manifest["total_collections_found"] = len(global_manifest["collections"])
        global_manifest["extraction_end_date"] = datetime.now().isoformat()
        
        # Ensure the base output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Construct the full path for the global manifest
        global_manifest_full_path = os.path.join(OUTPUT_DIR, "global-manifest.json")
        
        with open(global_manifest_full_path, "w", encoding="utf-8") as f:
            json.dump(global_manifest, f, ensure_ascii=False, indent=4)
        
        print(f"\nGlobal manifest saved to: {global_manifest_full_path}")
        print(f"Total unique collections discovered: {global_manifest['total_collections_found']}")

        await browser.close()
        print("Browser closed.")

if __name__ == "__main__":
    asyncio.run(discover_top_level_collections())