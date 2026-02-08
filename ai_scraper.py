import os
import time
import json
from typing import List
from google import genai
from pydantic import BaseModel, Field
from supabase import create_client, Client
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
SUPABASE_URL = "https://ienehkupdokrcjmfxtgj.supabase.co"
SUPABASE_KEY = "sb_secret_Phb71iHk6y6ghw-1Kbe_VA_BDV-dS-r"
GEMINI_API_KEY = "AIzaSyAh7vv6YG_qvA3r1Wsff7cYT57Jnm1mkiQ"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- LIST AVAILABLE MODELS ---
print("Available models:")
for m in genai_client.models.list():
    print(" -", m.name)
    if hasattr(m, "description"):
        print("   >", m.description)


# --- 1. CLEAN HTML HELPER ---
def get_clean_text(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for script in soup(["script", "style", "svg", "footer", "nav", "header", "noscript"]):
        script.decompose()
    text = soup.get_text(separator="\n")
    # Limit to first 7000 lines to prevent huge prompts
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()][:7000])

# --- 2. VALIDATE URL ---
def validate_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url

# --- 3. GEMINI CALL ---
def query_gemini(prompt: str) -> dict:
    try:
        response = genai_client.models.generate_content(
            model="models/gemini-2.5-flash",  # Updated model
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"   ❌ Gemini API error: {e}")
        return {}

# --- 4. MAIN SCRAPER ---
def run_gemini_scraper():
    response = supabase.table("buildings").select("*").neq("website_url", "null").execute()
    buildings = response.data

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for building in buildings:
            print(f"------------\nProcessing: {building['name']}")
            page = None
            try:
                context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.97 Safari/537.36")
                page = context.new_page()


                url = validate_url(building['website_url'])
                try:
                    page.goto(url, timeout=120000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError:
                    print(f"   ⚠ Timeout navigating to {url}, skipping page.")
                    continue

                # Scroll to bottom to load lazy content
                page.mouse.wheel(0, 5000)
                time.sleep(5)  # Let dynamic content load

                clean_text = get_clean_text(page.content())

                # --- Gemini Prompt ---
                prompt = f"""
                TEXT:
                Extract all apartment floorplans from the text below.
                Return the data as a JSON object with a key "units" containing a list of objects.
                Each object must have:
                - "unit_name": string
                - "bedrooms": integer (if unknown, use null)
                - "bathrooms": integer (if unknown, use null)
                - "price": integer (lowest if range, if unknown, use null)

                Make sure the JSON is valid and every field is filled with a value.
                TEXT:
                {clean_text}
                """

                raw_json = query_gemini(prompt)
                units_found = raw_json.get("units", [])
                print(f"   ✅ Found {len(units_found)} units!")

                # Insert units into Supabase
                for unit in units_found:
                    data = {
                        "building_id": building['id'],
                        "unit_name": unit.get('unit_name'),
                        "bedrooms": unit.get('bedrooms'),
                        "bathrooms": unit.get('bathrooms'),
                        "price": unit.get('price')
                    }
                    supabase.table("units").insert(data).execute()
                    print(f"      -> {unit.get('unit_name')}: ${unit.get('price')}")

            except Exception as e:
                print(f"   ❌ Error processing building: {e}")
            finally:
                if page:
                    page.close()

        browser.close()

if __name__ == "__main__":
    run_gemini_scraper()
