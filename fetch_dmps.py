import requests
import os
import time

# --- CONFIGURATION ---
QUERY_URL = "https://argos.openaire.eu/api/plan/public/query"
EXPORT_XML_URL = "https://argos.openaire.eu/api/plan/xml/export-public"
EXPORT_JSON_URL = "https://argos.openaire.eu/api/file-transformer/export-public-plan"
IDS_FILE = "dmp_ids.txt"
OUTPUT_DIR = "argos_exports"
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
            # "versionStatuses": [1],
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
# STEP 2 — Download XML + JSON exports
# ─────────────────────────────────────────────

def read_token_from_file():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        if token:
            return token
    return None


def get_download_headers(token, content_type="application/xml"):
    clean_token = token.replace("Bearer ", "").strip()
    return {
        "Authorization": f"Bearer {clean_token}",
        "Accept": content_type,
        "Content-Type": "application/json",
        "x-tenant": "default",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def wait_for_token_refresh(dmp_id, status_code):
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
    print(f"STEP 2: Downloading {total} DMP XML + JSON exports...")
    print("=" * 60)

    i = 0
    while i < total:
        dmp_id = dmp_ids[i]
        xml_path = os.path.join(OUTPUT_DIR, f"{dmp_id}.xml")
        json_path = os.path.join(OUTPUT_DIR, f"{dmp_id}.json")

        xml_done = os.path.exists(xml_path) and os.path.getsize(xml_path) > 0
        json_done = os.path.exists(json_path) and os.path.getsize(json_path) > 0

        if xml_done and json_done:
            print(f"[{i+1}/{total}] Skipping (both exist): {dmp_id}")
            i += 1
            continue

        # ── XML download ──────────────────────────────────────────
        if not xml_done:
            session.headers.update(get_download_headers(current_token, "application/xml"))
            try:
                response = session.get(f"{EXPORT_XML_URL}/{dmp_id}", timeout=30)

                if response.status_code == 200:
                    with open(xml_path, "wb") as f:
                        f.write(response.content)
                    print(f"[{i+1}/{total}] XML downloaded: {dmp_id}")

                elif response.status_code in [401, 403]:
                    current_token = wait_for_token_refresh(dmp_id, response.status_code)
                    session = requests.Session()
                    continue  # retry same DMP

                else:
                    print(f"[{i+1}/{total}] XML server error {response.status_code} on {dmp_id}. Skipping XML.")

            except requests.exceptions.RequestException as e:
                print(f"\nNetwork error (XML) on {dmp_id}: {e}. Retrying in 5s...")
                time.sleep(5)
                continue  # retry same DMP
        else:
            print(f"[{i+1}/{total}] XML already exists: {dmp_id}")

        # ── JSON download ─────────────────────────────────────────
        if not json_done:
            json_headers = get_download_headers(current_token, "application/json")
            json_payload = {
                "id": dmp_id,
                "repositoryId": "rda-file-transformer",
                "format": "json",
            }
            try:
                response = session.post(
                    EXPORT_JSON_URL,
                    headers=json_headers,
                    json=json_payload,
                    timeout=30,
                )

                if response.status_code == 200:
                    with open(json_path, "wb") as f:
                        f.write(response.content)
                    print(f"[{i+1}/{total}] JSON downloaded: {dmp_id}")

                elif response.status_code in [401, 403]:
                    current_token = wait_for_token_refresh(dmp_id, response.status_code)
                    session = requests.Session()
                    continue  # retry same DMP (both XML skip + JSON retry)

                else:
                    print(f"[{i+1}/{total}] JSON server error {response.status_code} on {dmp_id}. Skipping JSON.")

            except requests.exceptions.RequestException as e:
                print(f"\nNetwork error (JSON) on {dmp_id}: {e}. Retrying in 5s...")
                time.sleep(5)
                continue  # retry same DMP

        time.sleep(0.1)
        i += 1

    print(f"\nFinished! All files saved to '{OUTPUT_DIR}'.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ids, total = fetch_dmp_ids()

    if not ids:
        print("No DMP IDs found. Exiting.")
        return

    print(f"Total DMPs reported by API : {total}")
    print(f"Total IDs retrieved        : {len(ids)}")
    save_ids(ids, IDS_FILE)

    download_dmps(ids)


if __name__ == "__main__":
    main()