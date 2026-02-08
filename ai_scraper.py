import os
import time
import typing_extensions
from google import genai
from pydantic import BaseModel, Field
from typing import List
from supabase import create_client, Client
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
SUPABASE_URL = "https://ienehkupdokrcjmfxtgj.supabase.co"
SUPABASE_KEY = "sb_secret_Phb71iHk6y6ghw-1Kbe_VA_BDV-dS-r"
GEMINI_API_KEY = "AIzaSyBLfa108O5riVDnryu3aHh285G2CINnOVo"

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Gemini
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- 1. DEFINE THE DATA STRUCTURE ---
# Gemini will force the output to match this EXACTLY.
class ApartmentUnit(BaseModel):
    unit_name: str = Field(description="The name of the floorplan, e.g., 'The Rio', '4x4 Shared'")
    bedrooms: int = Field(description="Number of bedrooms")
    bathrooms: int = Field(description="Number of bathrooms")
    price: int = Field(description="Monthly rent in USD. If range, take lowest.")

class BuildingExtraction(BaseModel):
    units: List[ApartmentUnit]

# --- 2. CLEAN HTML HELPER ---
def get_clean_text(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    # Remove junk elements
    for script in soup(["script", "style", "svg", "footer", "nav", "header"]):
        script.decompose()
    # Get text
    text = soup.get_text(separator="\n")
    # Remove empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:6000]) # Gemini handles large context well

# --- 3. MAIN SCRAPER ---
def run_gemini_scraper():
    # Fetch buildings from Supabase that have a website
    response = supabase.table("buildings").select("*").neq("website_url", "null").execute()
    buildings = response.data

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        
        for building in buildings:
            print(f"------------\nProcessing: {building['name']}")
            
            try:
                # 1. Scrape Website
                page = browser.new_page()
                print(f"   🌍 Loading {building['website_url']}...")
                page.goto(building['website_url'], timeout=60000)
                
                # Scroll to trigger lazy loading
                page.mouse.wheel(0, 5000)
                time.sleep(3) 

                clean_text = get_clean_text(page.content())
                print(f"   📄 Extracted {len(clean_text)} characters of text.")

                # 2. Ask Gemini
                response = genai_client.models.generate_content(
                model="gemini-1.5-flash",
                contents=f"""
                Extract all apartment floorplans with:
                - unit_name
                - bedrooms
                - bathrooms
                - price (lowest if range)

                Return JSON ONLY matching the schema.

                TEXT:
                {clean_text}
                """,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": BuildingExtraction
                }
                )

                units_found = response.parsed.units


                # 3. Parse Response
                # Gemini returns a string, but because we enforced schema, we can parse it directly
                import json
                result_json = json.loads(response.text)
                
                # Depending on SDK version, result might be the dict or the list inside
                units_found = result_json.get("units", [])
                
                print(f"   ✅ Found {len(units_found)} units!")

                # 4. Upload to Supabase
                for unit in units_found:
                    print(f"      -> {unit['unit_name']}: ${unit['price']}")
                    
                    data = {
                        "building_id": building['id'],
                        "unit_name": unit['unit_name'],
                        "bedrooms": unit['bedrooms'],
                        "bathrooms": unit['bathrooms'],
                        "price": unit['price']
                    }
                    
                    # Insert into DB
                    supabase.table("units").insert(data).execute()

            except Exception as e:
                print(f"   ❌ Error: {e}")
            
            finally:
                page.close()
        
        browser.close()

if __name__ == "__main__":
    run_gemini_scraper()
