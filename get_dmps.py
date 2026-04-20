import requests
import os
import time

# --- CONFIGURATION ---
BASE_URL = "https://argos.openaire.eu/api/plan/xml/export-public"
IDS_FILE = "dmps.txt"
OUTPUT_DIR = "argos_xml_exports"
INITIAL_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJ2NFY5c3J6ekJYWG5UU19YM1MxZmVOWFN6YVRESVRxM1JpeHdqNXBXYjVnIn0.eyJleHAiOjE3NzY2Nzk5NTUsImlhdCI6MTc3NjY3OTY1NSwiYXV0aF90aW1lIjoxNzc2NjczMTg5LCJqdGkiOiIzNWNiMzA3MC1jZTgwLTQ2MWMtOTRkYi1jZTlmNTFlYmUyNWQiLCJpc3MiOiJodHRwczovL2FyZ29zLWF1dGgub3BlbmFpcmUuZXUvcmVhbG1zL0FyZ29zIiwiYXVkIjpbImRtcF9hbm5vdGF0aW9uIiwiZG1wX25vdGlmaWNhdGlvbiIsImRtcF93ZWIiXSwic3ViIjoiNTM4YzIwNzItZDc1Yi00MWVhLTllNjQtZjAyMzQzNTczNmZlIiwidHlwIjoiQmVhcmVyIiwiYXpwIjoiZG1wX3dlYmFwcCIsInNpZCI6ImEyNjliMDA1LTFmZGItNGVmZi1iNzNjLTdjMTBmYWQyNmFkZiIsImFjciI6IjAiLCJhbGxvd2VkLW9yaWdpbnMiOlsiaHR0cHM6Ly9hcmdvcy5vcGVuYWlyZS5ldSJdLCJyZXNvdXJjZV9hY2Nlc3MiOnsiZG1wX2Fubm90YXRpb24iOnsicm9sZXMiOlsiVXNlciJdfSwiZG1wX25vdGlmaWNhdGlvbiI6eyJyb2xlcyI6WyJVc2VyIl19LCJkbXBfd2ViIjp7InJvbGVzIjpbIlVzZXIiXX19LCJzY29wZSI6Im9wZW5pZCB0ZW5hbnRfcm9sZSBkbXBfd2ViIHBob25lIGFkZHJlc3MgaWRlbnRpdHlfcHJvdmlkZXIgcHJvZmlsZSBlbWFpbCIsImlkZW50aXR5X3Byb3ZpZGVyIjoib3BlbmFpcmUiLCJhZGRyZXNzIjp7fSwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJBbmRyZWEgTWFubm9jY2kiLCJ0ZW5hbnRfcm9sZXMiOlsiVGVuYW50VXNlcjpkZWZhdWx0Il0sInByZWZlcnJlZF91c2VybmFtZSI6ImFuZHJlYS5tYW5ub2NjaUBpc3RpLmNuci5pdCIsImdpdmVuX25hbWUiOiJBbmRyZWEiLCJmYW1pbHlfbmFtZSI6Ik1hbm5vY2NpIiwiZW1haWwiOiJhbmRyZWEubWFubm9jY2lAaXN0aS5jbnIuaXQifQ.nFKgl7Z56DaIz_IOHlCYk8-22qIPiOOXsJwP19PI-69Ye2Tm5B9eBqxZIFhXFCUetqLFqEFj4Cx4z3OXWm7_oI10swX_bW9d56LEJOsXQRJHZpgy3_43aJu39v-4qEWyQUSA6CpztdgdzDxy66MN_3IsuPlbEyMYB5a3NvgAeWVy2VPGS0mt0UqxpG1wnVNWxLcRNGEbvfPTnm9u5h8LPy8il2CVO75KDYdoLtp84sLOE4Oi5zzjELZq5qkhK2LcgiBE5j10exl4jHbp8oPMZBX4FAP_zyVnKj6m9F7xOt9offqncRRQkJACeYUpSvWsl_7c6fXqeZC1W1r8uLT6oA"

def get_headers(token):
    # Cleans the token string to ensure no double-prefixes
    clean_token = token.replace("Bearer ", "").strip()
    return {
        'Authorization': f'Bearer {clean_token}',
        'Accept': 'application/xml',
        'x-tenant': 'default',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

def download_dmps():
    # Ensure the output folder exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Read the IDs from your file
    if not os.path.exists(IDS_FILE):
        print(f"Error: {IDS_FILE} not found!")
        return

    with open(IDS_FILE, 'r') as f:
        dmp_ids = [line.strip() for line in f if line.strip()]

    current_token = INITIAL_TOKEN
    total = len(dmp_ids)
    session = requests.Session()
    
    i = 0
    while i < total:
        dmp_id = dmp_ids[i]
        file_path = os.path.join(OUTPUT_DIR, f"{dmp_id}.xml")
        
        # --- SKIP LOGIC ---
        if os.path.exists(file_path):
            # Optional: check if file is non-empty
            if os.path.getsize(file_path) > 0:
                print(f"[{i+1}/{total}] Skipping (Already exists): {dmp_id}")
                i += 1
                continue
        # ------------------

        session.headers.update(get_headers(current_token))
        
        try:
            # 30s timeout to handle the 'Read Timeout' errors from the server
            response = session.get(f"{BASE_URL}/{dmp_id}", timeout=30)
            
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                print(f"[{i+1}/{total}] Success: {dmp_id}")
                i += 1
                time.sleep(0.1) 
            
            elif response.status_code in [401, 403]:
                print(f"\n--- AUTH ERROR (Status {response.status_code}) ---")
                print(f"Occurred at ID: {dmp_id}")
                new_input = input("Paste fresh token and hit ENTER (or type 'skip'): ").strip()
                
                if new_input.lower() == 'skip':
                    print(f"Skipping {dmp_id} manually...")
                    i += 1
                else:
                    current_token = new_input
                    session = requests.Session() # Fully reset session for the new token
                    print("--- Resuming with new token ---\n")
            
            else:
                print(f"[{i+1}/{total}] Server error {response.status_code} on {dmp_id}. Skipping.")
                i += 1

        except requests.exceptions.RequestException as e:
            print(f"\nNetwork delay/error on {dmp_id}: {e}")
            print("Retrying in 5 seconds...")
            time.sleep(5)

    print(f"\nFinished! All possible files are in '{OUTPUT_DIR}'.")

if __name__ == "__main__":
    download_dmps()