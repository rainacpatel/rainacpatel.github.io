import os
import json
from typing import List
from pydantic import BaseModel, Field
import instructor
from openai import OpenAI
from supabase import create_client, Client
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
SUPABASE_URL = "https://ienehkupdokrcjmfxtgj.supabase.co"
SUPABASE_KEY = "sb_secret_Phb71iHk6y6ghw-1Kbe_VA_BDV-dS-r"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"  # sk-proj-..."

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = instructor.from_openai(OpenAI(api_key=OPENAI_API_KEY))

# --- 1. DEFINE WHAT WE WANT (THE SCHEMA) ---
# This tells the AI exactly what format to output.
class ApartmentUnit(BaseModel):
    unit_name: str = Field(..., description="The name of the floorplan, e.g., 'The rIO', '4x4 Shared'")
    bedrooms: int = Field(..., description="Number of bedrooms")
    bathrooms: int = Field(..., description="Number of bathrooms")
    price: int = Field(..., description="Monthly rent in USD. If a range is given, take the lowest number.")

class BuildingExtraction(BaseModel):
    units: List[ApartmentUnit]

# --- 2. CLEAN THE HTML ---
def get_clean_text(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    # Remove junk we don't need to read
    for script in soup(["script", "style", "svg", "footer", "nav"]):
        script.decompose()
    # Get text
    text = soup.get_text(separator="\n")
    # Remove empty lines to save tokens
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:4000]) # Limit to ~4000 lines to avoid token limits

# --- 3. THE MAIN LOOP ---
def run_ai_scraper():
    # Get buildings that have a website
    response = supabase.table("buildings").select("*").neq("website_url", "null").execute()
    buildings = response.data

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Set False if you want to watch
        
        for building in buildings:
            print(f"------------\n🏢 Processing: {building['name']}")
            
            # 1. Scrape Raw HTML
            page = browser.new_page()
            try:
                print(f"   Browsing {building['website_url']}...")
                page.goto(building['website_url'], timeout=30000)
                
                # Scroll down to trigger lazy-loading images/prices
                page.mouse.wheel(0, 4000) 
                page.wait_for_timeout(2000) # Wait a bit
                
                html = page.content()
                clean_text = get_clean_text(html)
                
                print("   🤖 Sending to AI for extraction...")

                # 2. Ask AI to find the units
                extraction = client.chat.completions.create(
                    model="gpt-4o-mini", # Cheap and fast model
                    response_model=BuildingExtraction,
                    messages=[
                        {
                            "role": "system", 
                            "content": "You are a data extractor. Extract apartment floorplan data from the following website text. Ignore parking or generic fees."
                        },
                        {
                            "role": "user", 
                            "content": clean_text
                        }
                    ],
                )

                # 3. Upload to Supabase
                units_found = extraction.units
                print(f"   AI found {len(units_found)} units!")

                for unit in units_found:
                    # Prepare data row
                    data = {
                        "building_id": building['id'],
                        "unit_name": unit.unit_name,
                        "bedrooms": unit.bedrooms,
                        "bathrooms": unit.bathrooms,
                        "price": unit.price
                    }
                    print(f"      -> {unit.unit_name}: ${unit.price}")
                    
                    # Insert (Simple insert, you might want to check for duplicates later)
                    supabase.table("units").insert(data).execute()

            except Exception as e:
                print(f"   Error: {e}")
            
            finally:
                page.close()
        
        browser.close()

if __name__ == "__main__":
    run_ai_scraper()
