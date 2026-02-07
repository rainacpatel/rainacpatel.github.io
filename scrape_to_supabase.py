import os
from serpapi import GoogleSearch
from supabase import create_client, Client

# --- 1. CONFIGURATION ---
# Get these from your Supabase Dashboard -> Settings -> API
SUPABASE_URL = "https://ienehkupdokrcjmfxtgj.supabase.co"
# IMPORTANT: Use the "service_role" key here (it bypasses Row Level Security), 
# NOT the "anon" key. Keep this key secret!
SUPABASE_KEY = "sb_secret_Phb71iHk6y6ghw-1Kbe_VA_BDV-dS-r" 

# Get this from SerpAPI.com
SERPAPI_KEY = "9473b35ade77a364d911b7a351cc886c284a8ed91ccd4bb28fff25835421ebb2"

# Initialize connection to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_and_upload():
    print("Starting scrape...")
    
    # Search for apartments in West Campus
    params = {
        "engine": "google_maps",
        "q": "Student Apartments in West Campus, Austin, TX",
        "ll": "@30.286,-97.742,15z", # West Campus Coordinates
        "type": "search",
        "api_key": SERPAPI_KEY,
        "limit": 20 # How many results to fetch
    }

    search = GoogleSearch(params)
    results = search.get_dict()
    local_results = results.get("local_results", [])

    print(f"Found {len(local_results)} buildings on Google Maps.")

    for place in local_results:
        # 1. Extract Data
        name = place.get("title")
        address = place.get("address")
        website = place.get("website")
        gps = place.get("gps_coordinates", {})
        
        # Skip if data is messy (missing location)
        if not gps.get("latitude"):
            continue

        print(f"   Uploading: {name}")

        # 2. Prepare the row for Supabase
        building_data = {
            "name": name,
            "address": address,
            "website_url": website,
            "lat": gps.get("latitude"),
            "lng": gps.get("longitude")
        }

        # 3. Insert into Supabase 'buildings' table
        try:
            # We use 'upsert' to avoid duplicates if you run this script twice
            # Note: This requires a unique constraint on 'name' or 'address' in your DB,
            # otherwise it will just keep adding duplicates. 
            # For MVP, a simple insert is fine if you empty the table first.
            supabase.table("buildings").insert(building_data).execute()

        except Exception as e:
            print(f"      Error: {e}")

    print("Done! Data is now in Supabase.")

if __name__ == "__main__":
    fetch_and_upload()