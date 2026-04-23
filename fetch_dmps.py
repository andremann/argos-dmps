import requests
import os
import time

# --- CONFIGURATION ---
QUERY_URL = "https://argos.openaire.eu/api/plan/public/query"
EXPORT_URL = "https://argos.openaire.eu/api/plan/xml/export-public"
IDS_FILE = "dmp_ids.txt"
OUTPUT_DIR = "argos_xml_exports"
TOKEN_FILE = "token.txt"  # <-- Paste your fresh token here when it expires

PAGE_SIZE = 1000

QUERY_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://argos.openaire.eu",
    "Pragma": "no-cache",
    "Referer": "https://argos.openaire.eu/api/swagger-ui/index.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "accept": "*/*",
    "x-tenant": "default",
}

# ─────────────────────────────────────────────
# STEP 1 — Fetch & save DMP IDs
# ─────────────────────────────────────────────

def fetch_dmp_ids():
    all_ids = []
    offset = 0

    print("=" * 60)
    print("STEP 1: Fetching DMP IDs from OpenAIRE Argos...")
    print("=" * 60)

    while True:
        payload = {
            "project": {"fields": ["id"]},
            "metadata": {"countAll": True},
            "page": {"offset": offset, "size": PAGE_SIZE},
            "isActive": [1],
            # "versionStatuses": [1], # <-- Uncomment if you want to filter by version status (e.g., only the last version of each DMP) 
            "order": {"items": ["-updatedAt"]},
            "groupIds": None,
        }

        response = requests.post(QUERY_URL, headers=QUERY_HEADERS, json=payload)
        response.raise_for_status()

        data = response.json()
        items = data.get("items", [])
        total = data.get("count", 0)

        ids = [item["id"] for item in items if "id" in item]
        all_ids.extend(ids)

        print(f"  Fetched {len(all_ids)} / {total} IDs...")

        if offset + PAGE_SIZE >= total:
            break
        offset += PAGE_SIZE

    return all_ids, total


def save_ids(ids, filepath):
    with open(filepath, "w") as f:
        for dmp_id in ids:
            f.write(dmp_id + "\n")
    print(f"\nSaved {len(ids)} IDs to '{filepath}'\n")


# ─────────────────────────────────────────────
# STEP 2 — Download XML exports
# ─────────────────────────────────────────────

def read_token_from_file():
    """Read token from TOKEN_FILE if it exists and is non-empty."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        if token:
            return token
    return None


def get_download_headers(token):
    clean_token = token.replace("Bearer ", "").strip()
    return {
        "Authorization": f"Bearer {clean_token}",
        "Accept": "application/xml",
        "x-tenant": "default",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def wait_for_token_refresh(dmp_id, status_code):
    """Pause until the user pastes a new token into TOKEN_FILE."""
    print(f"\n{'='*60}")
    print(f"  AUTH ERROR (HTTP {status_code}) on DMP: {dmp_id}")
    print(f"{'='*60}")
    print(f"  Your token has expired. To continue:")
    print(f"  1. Log in to https://argos.openaire.eu and go to the public DMPs page")
    print(f"  2. Open the browser inspector and go on the Network tab")
    print(f"  3. Refresh the page or download a DMP XML in order to fire an API call with a Bearer token in the header")
    print(f"  4. Copy your new Bearer token")
    print(f"  5. Paste it (just the token, no 'Bearer ' prefix) into:")
    print(f"     {os.path.abspath(TOKEN_FILE)}")
    print(f"  The script will resume automatically once it detects the new token.")
    print(f"{'='*60}\n")

    old_token = read_token_from_file()

    while True:
        time.sleep(5)
        new_token = read_token_from_file()
        if new_token and new_token != old_token:
            print("  New token detected — resuming download...\n")
            return new_token
        print("  Waiting for new token in token.txt ...")


def download_dmps(dmp_ids):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    current_token = read_token_from_file()
    if not current_token:
        print("\nNo token found in token.txt.")
        print("Please paste your Bearer token into token.txt and re-run the script.\n")
        return

    total = len(dmp_ids)
    session = requests.Session()

    print("=" * 60)
    print(f"STEP 2: Downloading {total} DMP XML exports...")
    print("=" * 60)

    i = 0
    while i < total:
        dmp_id = dmp_ids[i]
        file_path = os.path.join(OUTPUT_DIR, f"{dmp_id}.xml")

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            print(f"[{i+1}/{total}] Skipping (already exists): {dmp_id}")
            i += 1
            continue

        session.headers.update(get_download_headers(current_token))

        try:
            response = session.get(f"{EXPORT_URL}/{dmp_id}", timeout=30)

            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(response.content)
                print(f"[{i+1}/{total}] Downloaded: {dmp_id}")
                i += 1
                time.sleep(0.1)

            elif response.status_code in [401, 403]:
                current_token = wait_for_token_refresh(dmp_id, response.status_code)
                session = requests.Session()
                # Do NOT increment i — retry same DMP with new token

            else:
                print(f"[{i+1}/{total}] Server error {response.status_code} on {dmp_id}. Skipping.")
                i += 1

        except requests.exceptions.RequestException as e:
            print(f"\nNetwork error on {dmp_id}: {e}")
            print("Retrying in 5 seconds...")
            time.sleep(5)

    print(f"\nFinished! All files saved to '{OUTPUT_DIR}'.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    # Step 1: fetch and save IDs
    ids, total = fetch_dmp_ids()

    if not ids:
        print("No DMP IDs found. Exiting.")
        return

    print(f"Total DMPs reported by API : {total}")
    print(f"Total IDs retrieved        : {len(ids)}")
    save_ids(ids, IDS_FILE)

    # Step 2: download XMLs
    download_dmps(ids)


if __name__ == "__main__":
    main()