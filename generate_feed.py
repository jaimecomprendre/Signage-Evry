import os
import time
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from xml.dom import minidom

from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

MEDIA_DIR = "/media"
OUTPUT_DIR = "/app/rss"
BASE_URL = os.environ.get("BASE_URL", "http://10.35.69.41:8000")
FEED_TITLE = "Auto Signage Feed"
POLL_INTERVAL = 10       # seconds between watchdog scans
FORCE_REGEN_INTERVAL = 30  # seconds between forced full regeneration
SUPPORTED_EXTENSIONS = {
    ".jpg":  ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".png":  ("image/png",  "image"),
    ".mp4":  ("video/mp4",  "video"),
}

# Lock to avoid simultaneous regenerations
regen_lock = threading.Lock()


def get_file_size(filepath):
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


def slugify_guid(filename, index):
    stem = os.path.splitext(filename)[0].lower().replace(" ", "_")
    return f"{stem}_{index:04d}"


def build_feed(folder_path, folder_name):
    ET.register_namespace("media", "http://search.yahoo.com/mrss/")
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:media": "http://search.yahoo.com/mrss/",
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{FEED_TITLE} - {folder_name}"

    filenames = sorted(os.listdir(folder_path))
    item_count = 0

    for filename in filenames:
        filepath = os.path.join(folder_path, filename)

        # Skip directories and tiny/incomplete files (avoids 4096-byte false positives)
        if not os.path.isfile(filepath):
            continue
        if os.path.getsize(filepath) < 5000:
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        mime_type, medium = SUPPORTED_EXTENSIONS[ext]
        # URL-encode folder and filename to handle spaces and special characters
        encoded_folder = urllib.parse.quote(folder_name)
        encoded_filename = urllib.parse.quote(filename)
        file_url = f"{BASE_URL}/media/{encoded_folder}/{encoded_filename}"
        file_size = get_file_size(filepath)
        item_count += 1
        guid = slugify_guid(filename, item_count)

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = filename
        ET.SubElement(item, "link").text = file_url
        ET.SubElement(item, "description").text = file_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = guid
        ET.SubElement(item, "media:content", {
            "url":      file_url,
            "fileSize": str(file_size),
            "type":     mime_type,
            "medium":   medium,
        })

    if item_count == 0:
        print(f"[WARNING] No media found in '{folder_name}'")

    raw_xml = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(raw_xml)
    pretty = dom.toprettyxml(indent="  ", encoding=None)
    lines = pretty.split("\n")
    lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    return "\n".join(lines)


def generate_all_feeds():
    with regen_lock:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        subfolders = [
            f for f in os.listdir(MEDIA_DIR)
            if os.path.isdir(os.path.join(MEDIA_DIR, f))
        ]

        if not subfolders:
            print("[WARNING] No subfolders found in media directory")
            return

        for folder_name in subfolders:
            folder_path = os.path.join(MEDIA_DIR, folder_name)
            output_file = os.path.join(OUTPUT_DIR, f"feed-{folder_name}.xml")
            print(f"[INFO] Regenerating feed for '{folder_name}' ...")
            feed_content = build_feed(folder_path, folder_name)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(feed_content)
            print(f"[OK]   '{output_file}' written.")


def force_regen_loop():
    """Periodically regenerate all feeds regardless of watchdog events."""
    while True:
        time.sleep(FORCE_REGEN_INTERVAL)
        print(f"[TIMER] Forced regeneration every {FORCE_REGEN_INTERVAL}s...")
        generate_all_feeds()


class MediaChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if event.is_directory:
            return
        if os.path.basename(event.src_path).startswith("."):
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return
        print(f"[EVENT] {event.event_type}: {event.src_path}")
        generate_all_feeds()


if __name__ == "__main__":
    print("[START] Generating initial feeds...")
    generate_all_feeds()

    # Start forced regeneration timer in background
    timer_thread = threading.Thread(target=force_regen_loop, daemon=True)
    timer_thread.start()

    print(f"[WATCH] Polling '{MEDIA_DIR}' every {POLL_INTERVAL}s for changes...")
    handler = MediaChangeHandler()
    observer = PollingObserver(timeout=POLL_INTERVAL)
    observer.schedule(handler, MEDIA_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
