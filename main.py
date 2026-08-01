import os
import sys
import time
import json
import threading
import requests
from flask import Flask

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
SEEDR_EMAIL = os.environ.get("SEEDR_EMAIL", "sbt.console@gmail.com")
SEEDR_PASS = os.environ.get("SEEDR_PASS", "Admin@123")
GDRIVE_WEBHOOK_URL = os.environ.get("GDRIVE_WEBHOOK_URL", "https://script.google.com/macros/s/AKfycbzSHqtAKu1CaNZxKaE4GWvgZRbLJTXCBU83S4KXNlrlNQp498PL2OuimHEJaueZzMAj/exec")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "15"))

SEEDR_BASE_URL = "https://www.seedr.cc"

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Seedr 24/7 Auto-Sync Cloud Bot is Active & Running!", 200

@app.route('/health')
def health():
    return "OK", 200

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

def login_seedr():
    print(f"🔑 [Cloud Bot] Logging into Seedr ({SEEDR_EMAIL})...")
    login_url = f"{SEEDR_BASE_URL}/auth/login"
    payload = {
        "username": SEEDR_EMAIL,
        "password": SEEDR_PASS,
        "rememberme": "on"
    }
    try:
        res = session.post(login_url, data=payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if data.get("result") is True or data.get("user_id") or "RSESS_session" in session.cookies:
                print("✅ [Cloud Bot] Seedr Login Successful!")
                return True
    except Exception as e:
        print(f"❌ [Cloud Bot] Exception during Seedr login: {e}")
    return False

def get_seedr_items(folder_id=0):
    url = f"{SEEDR_BASE_URL}/api/v0.1/fs/folder/{folder_id}/items"
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"⚠️ Error fetching folder {folder_id}: {e}")
    return None

def get_file_download_url(file_id):
    url = f"{SEEDR_BASE_URL}/api/v0.1/download/file/{file_id}/url"
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("url")
    except Exception as e:
        print(f"⚠️ Error getting download URL for file {file_id}: {e}")
    return None

def delete_seedr_file(file_id):
    url = f"{SEEDR_BASE_URL}/api/v0.1/fs/batch/delete"
    delete_payload = {
        "delete_arr": json.dumps([{"type": "file", "id": file_id}])
    }
    try:
        res = session.post(url, data=delete_payload, timeout=15)
        if res.status_code == 200:
            print(f"🗑️ [Cloud Bot] Deleted file ID {file_id} from Seedr. 2 GB Space Freed!")
            return True
    except Exception as e:
        print(f"⚠️ Error deleting file {file_id}: {e}")
    return False

def delete_seedr_folder(folder_id):
    url = f"{SEEDR_BASE_URL}/api/v0.1/fs/batch/delete"
    delete_payload = {
        "delete_arr": json.dumps([{"type": "folder", "id": folder_id}])
    }
    try:
        res = session.post(url, data=delete_payload, timeout=15)
        if res.status_code == 200:
            print(f"🗑️ [Cloud Bot] Deleted folder ID {folder_id} from Seedr. Space Freed!")
            return True
    except Exception as e:
        print(f"⚠️ Error deleting folder {folder_id}: {e}")
    return False

processed_file_ids = set()

def stream_upload_resumable(dl_url, filename, upload_url):
    """Streams file chunk-by-chunk from Seedr directly to Google Drive Resumable Upload URL (No 50MB Limit!)"""
    try:
        head = session.head(dl_url, allow_redirects=True, timeout=15)
        total_size = int(head.headers.get("Content-Length", 0))
        
        print(f"🚀 [Cloud Bot] Starting Resumable Stream Upload for {filename} ({total_size / (1024*1024):.1f} MB)...")
        
        chunk_size = 8 * 1024 * 1024  # 8 MB chunks
        
        with session.get(dl_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            offset = 0
            
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                
                chunk_len = len(chunk)
                start = offset
                end = offset + chunk_len - 1
                
                headers = {
                    "Content-Length": str(chunk_len),
                    "Content-Range": f"bytes {start}-{end}/{total_size if total_size > 0 else '*'}"
                }
                
                put_res = requests.put(upload_url, data=chunk, headers=headers, timeout=120)
                offset += chunk_len
                
                if total_size > 0:
                    pct = int((offset / total_size) * 100)
                    print(f"  ⬆️ Uploaded {offset / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({pct}%)")
                else:
                    print(f"  ⬆️ Uploaded {offset / (1024*1024):.1f} MB...")
                
                if put_res.status_code in [200, 201]:
                    print(f"✅ [Cloud Bot] 100% Upload Completed for {filename}!")
                    return True
                elif put_res.status_code != 308:
                    print(f"⚠️ Unexpected status chunk PUT: {put_res.status_code} - {put_res.text}")
            
            print(f"✅ [Cloud Bot] Resumable Upload finished for {filename}!")
            return True
    except Exception as e:
        print(f"❌ [Cloud Bot] Stream upload exception: {e}")
    return False

def upload_to_gdrive_webhook(file_url, filename):
    """Triggers Google Apps Script Webhook for Resumable Stream Upload or Direct Fallback"""
    if not GDRIVE_WEBHOOK_URL:
        print("ℹ️ [Cloud Bot] GDRIVE_WEBHOOK_URL not set yet. Skipping Google Drive upload.")
        return False
    
    print(f"☁️ [Cloud Bot] Requesting Google Drive Resumable Upload for {filename}...")
    try:
        req_payload = {"action": "create_upload_url", "name": filename}
        res = requests.post(GDRIVE_WEBHOOK_URL, json=req_payload, timeout=30)
        
        if res.status_code == 200:
            data = res.json()
            upload_url = data.get("upload_url")
            if upload_url:
                return stream_upload_resumable(file_url, filename, upload_url)
    except Exception as e:
        print(f"⚠️ Resumable URL request failed: {e}. Falling back to direct POST...")
    
    # Fallback to direct POST
    try:
        payload = {"url": file_url, "name": filename}
        res = requests.post(GDRIVE_WEBHOOK_URL, json=payload, timeout=60)
        if res.status_code in [200, 302]:
            print(f"✅ [Cloud Bot] Successfully saved {filename} to Google Drive!")
            return True
    except Exception as e:
        print(f"⚠️ Error in fallback upload: {e}")
    return False

def process_folder(folder_id=0):
    items = get_seedr_items(folder_id)
    if not items:
        return

    files = items.get("files", [])
    folders = items.get("folders", [])

    for f in files:
        file_id = f.get("folder_file_id") or f.get("id")
        filename = f.get("name")
        size = f.get("size", 0)

        if file_id in processed_file_ids:
            continue

        print(f"\n⚡ [Cloud Bot] Completed File Found: {filename} ({size / (1024*1024):.1f} MB)")
        dl_url = get_file_download_url(file_id)

        if dl_url:
            print(f"🔗 Direct Download URL Ready: {dl_url}")
            success = upload_to_gdrive_webhook(dl_url, filename)
            if success:
                processed_file_ids.add(file_id)
                print("🧹 Auto-cleaning Seedr storage...")
                delete_seedr_file(file_id)

    for subfolder in folders:
        sub_id = subfolder.get("id")
        process_folder(sub_id)
        if folder_id == 0 and sub_id:
            delete_seedr_folder(sub_id)

def worker_loop():
    print("🚀 [Cloud Bot] Background Worker Started!")
    if not login_seedr():
        print("❌ Seedr login failed in cloud worker.")
        return

    while True:
        try:
            process_folder(0)
        except Exception as e:
            print(f"⚠️ Error in worker loop: {e}")
        time.sleep(CHECK_INTERVAL)

def start_background_worker():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

if __name__ == "__main__":
    start_background_worker()
    port = int(os.environ.get("PORT", 8080))
    print(f"🌐 [Cloud Bot] Web Server listening on port {port}...")
    app.run(host="0.0.0.0", port=port)
