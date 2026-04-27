#!/usr/bin/env python3
import requests
import time
import subprocess
import os
import argparse
import hashlib
import json
import sys
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

API_KEY = os.environ['LEANPUB_API_KEY']

BOOKS = [
    "learning-hammerspoon",
    "learning-cfengine",
    "emacs-org-leanpub",
    "lit-config"
]

POLL_INTERVAL = 30
NOTIFICATION_TIMEOUT_MS = 5000

DROPBOX_DIR = os.path.expanduser("~/Dropbox/Leanpub")
CACHE_DIR = os.path.expanduser("~/.cache/leanpub-covers")
os.makedirs(CACHE_DIR, exist_ok=True)

last_status = {}
DEBUG = False


# -----------------------------
# Helpers
# -----------------------------

def redact_url(url):
    parts = urlsplit(url)
    query = urlencode(
        [
            (key, "REDACTED" if key == "api_key" else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def redact_text(text):
    return str(text).replace(API_KEY, "REDACTED")


def debug(message):
    if DEBUG:
        timestamp = datetime.now().isoformat(timespec="seconds")
        print(f"[{timestamp}] DEBUG {redact_text(message)}", file=sys.stderr)


def debug_response(label, url, response, include_body=True):
    if not DEBUG:
        return

    debug(f"{label}: GET {redact_url(url)}")
    debug(f"{label}: response status={response.status_code} reason={response.reason}")
    if include_body:
        debug(f"{label}: response body={response.text}")


def cover_cache_path(slug, cover_url):
    digest = hashlib.sha256(cover_url.encode("utf-8")).hexdigest()[:12]
    ext = os.path.splitext(urlsplit(cover_url).path)[1] or ".png"
    return os.path.join(CACHE_DIR, f"{slug}-{digest}{ext}")


def book_info_cache_path(slug):
    return os.path.join(CACHE_DIR, f"{slug}-book-info.json")


def get_book_info(slug):
    cache_path = book_info_cache_path(slug)

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            debug(f"{slug} book info: loaded from cache {cache_path}")
            return data
        except Exception as e:
            debug(f"{slug} book info: failed to read cache: {e}")

    url = f"https://leanpub.com/{slug}.json?api_key={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        debug_response(f"{slug} book info", url, r)
        r.raise_for_status()
        data = r.json()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        debug(f"{slug} book info: cached at {cache_path}")
        return data
    except Exception as e:
        debug(f"{slug} book info: request failed: {e}")
        return None

def get_cover(slug):
    book_info = get_book_info(slug)
    if not book_info:
        return None

    cover_url = book_info.get("title_page_url")
    if not cover_url:
        debug(f"{slug} cover: no title_page_url in book info response")
        return None

    path = cover_cache_path(slug, cover_url)

    if not os.path.exists(path):
        try:
            r = requests.get(cover_url, timeout=10)
            debug_response(f"{slug} cover", cover_url, r, include_body=False)
            r.raise_for_status()
            if r.status_code == 200:
                with open(path, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            debug(f"{slug} cover: request failed: {e}")

    return path if os.path.exists(path) else None

def get_title(slug):
    book_info = get_book_info(slug)
    if not book_info:
        return None
    return book_info.get("title", None)

def open_book_folder(slug):
    path = os.path.join(DROPBOX_DIR, slug)
    if os.path.exists(path):
        subprocess.Popen(["xdg-open", path])


def notify(slug, message, icon=None, extra_args=[]):
    book_title = get_title(slug)
    if book_title:
        notification_title = f"{book_title} ({slug})"
    else:
        notification_title = slug
        
    cmd = [
        "notify-send",
        "-a", "Leanpub",
        "-t", str(NOTIFICATION_TIMEOUT_MS),
        notification_title,
        message
    ]

    if icon:
        cmd.extend(["-h", f"string:image-path:{icon}"])

    cmd.extend(extra_args)
    
    debug(f"Generating notification: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    debug(f"Notification output: {result}")
    return result.stdout.strip()


def notify_with_action(slug, message, icon=None):
    result = notify(slug, message, icon, ["-A", "open=Reveal in Dropbox folder"])
    debug(f"Action selectd = {result}")


def get_status(slug):
    url = f"https://leanpub.com/{slug}/job_status.json?api_key={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        debug_response(f"{slug} status", url, r)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        debug(f"{slug} status: request failed: {e}")
        return {"error": redact_text(e)}


def interpret(status_json):
    if "error" in status_json:
        return "error"
    status = status_json.get("status", "unknown")
    debug(f"interpreted status: {status}")
    
    return status


def format_status(status_json):
    """
    Build a message like:
    "3/10 Generating PDF"
    """
    if "error" in status_json:
        return f"Error: {status_json['error']}"

    status = status_json.get("status")

    if status == "working":
        step = status_json.get("num")
        total = status_json.get("total")
        message = status_json.get("message", "")

        if step and total:
            return f"{step}/{total} {message}"
        return message or "Working..."

    if status == "complete":
        return "Build finished successfully"

    if status == "failed":
        return status_json.get("message", "Build failed")

    return status or "unknown"


# -----------------------------
# Main loop
# -----------------------------

def main():
    global last_status
    global DEBUG

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print API request and response debugging information to stderr.",
    )
    args = parser.parse_args()
    DEBUG = args.debug

    debug("debug logging enabled")
    debug(f"poll interval (POLL_INTERVAL) = {POLL_INTERVAL}")
    debug(f"notification timeout (NOTIFICATION_TIMEOUT_MS) = {NOTIFICATION_TIMEOUT_MS}")

    while True:
        for slug in BOOKS:
            debug(f"---------")
            data = get_status(slug)
            state = interpret(data)
            message = format_status(data)
            debug(f"status message: {message}")
            
            prev = last_status.get(slug)

            # Avoid notifications on first run
            if prev is None:
                last_status[slug] = message
                continue

            if prev != message:
                icon = get_cover(slug)
                if message == "unknown":
                    notify_with_action(slug, "Build finished successfully", icon)
                else:
                    notify(slug, message, icon)
                last_status[slug] = message

            
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
