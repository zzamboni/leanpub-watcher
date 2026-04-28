#!/usr/bin/env python3
#
# leanpub-watcher
#
# Diego Zamboni, 2026
#
# https://github.com/zzamboni/leanpub-watcher
#

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

API_KEY = os.environ.get("LEANPUB_API_KEY")

DEFAULT_BOOKS = []

DEFAULT_POLL_INTERVAL = 30
DEFAULT_ACTIVE_POLL_INTERVAL = 5
DEFAULT_NOTIFICATION_TIMEOUT_MS = 10000
DEFAULT_DROPBOX_TYPE = "personal"
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/leanpub-watcher/config.json")

CACHE_DIR = os.path.expanduser("~/.cache/leanpub-covers")
os.makedirs(CACHE_DIR, exist_ok=True)

BOOKS = list(DEFAULT_BOOKS)
POLL_INTERVAL = DEFAULT_POLL_INTERVAL
ACTIVE_POLL_INTERVAL = DEFAULT_ACTIVE_POLL_INTERVAL
NOTIFICATION_TIMEOUT_MS = DEFAULT_NOTIFICATION_TIMEOUT_MS
last_status = {}
last_status_json = {}
DEBUG = False
DROPBOX_PATH = None
DROPBOX_TYPE = DEFAULT_DROPBOX_TYPE
next_poll_at = {}


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
    text = str(text)
    if API_KEY:
        return text.replace(API_KEY, "REDACTED")
    return text


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


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config file must contain a JSON object")
    return data


def apply_config(config):
    global API_KEY
    global BOOKS
    global POLL_INTERVAL
    global ACTIVE_POLL_INTERVAL
    global NOTIFICATION_TIMEOUT_MS
    global DROPBOX_TYPE
    global DROPBOX_PATH

    api_key = config.get("leanpub_api_key")
    if api_key is not None:
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("'leanpub_api_key' must be a non-empty string")
        API_KEY = api_key

    books = config.get("books")
    if books is not None:
        if (
            not isinstance(books, list)
            or not books
            or not all(isinstance(book, str) and book for book in books)
        ):
            raise ValueError("'books' must be a non-empty list of strings")
        BOOKS = books

    poll_interval = config.get("poll_interval")
    if poll_interval is not None:
        if not isinstance(poll_interval, int) or poll_interval <= 0:
            raise ValueError("'poll_interval' must be a positive integer")
        POLL_INTERVAL = poll_interval

    active_poll_interval = config.get("active_poll_interval")
    if active_poll_interval is not None:
        if not isinstance(active_poll_interval, int) or active_poll_interval <= 0:
            raise ValueError("'active_poll_interval' must be a positive integer")
        ACTIVE_POLL_INTERVAL = active_poll_interval

    notification_timeout_ms = config.get("notification_timeout_ms")
    if notification_timeout_ms is not None:
        if not isinstance(notification_timeout_ms, int) or notification_timeout_ms < 0:
            raise ValueError("'notification_timeout_ms' must be a non-negative integer")
        NOTIFICATION_TIMEOUT_MS = notification_timeout_ms

    dropbox_type = config.get("dropbox_type")
    if dropbox_type is not None:
        if dropbox_type not in {"personal", "business"}:
            raise ValueError("'dropbox_type' must be 'personal' or 'business'")
        DROPBOX_TYPE = dropbox_type
        DROPBOX_PATH = None


def get_dropbox_path():
    global DROPBOX_PATH

    if DROPBOX_PATH:
        return DROPBOX_PATH

    info_path = os.path.expanduser("~/.dropbox/info.json")
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            dropbox_data = json.load(f)
        profile = dropbox_data.get(DROPBOX_TYPE)
        if profile and profile.get("path"):
            DROPBOX_PATH = profile["path"]
            debug(f"Dropbox path ({DROPBOX_TYPE}) = {DROPBOX_PATH}")
            return DROPBOX_PATH
        debug(f"Dropbox profile '{DROPBOX_TYPE}' not found in {info_path}")
    except Exception as e:
        debug(f"Could not determine Dropbox path from {info_path}: {e}")

    return None


def get_book_output_path(slug, job_type):
    dropbox_path = get_dropbox_path()
    if not dropbox_path:
        return None

    subdir = ""
    if job_type:
        if "preview" in job_type:
            subdir = "preview"
        elif "publish" in job_type or "EmailPossibleReaders" in job_type:
            subdir = "published"

    path = os.path.join(dropbox_path, f"{slug}-output")
    if subdir:
        path = os.path.join(path, subdir)

    debug(f"{slug} output path for job_type={job_type!r}: {path}")
    return path


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


def open_book_folder(slug, status_json):
    path = get_book_output_path(slug, status_json.get("job_type"))
    if not path:
        debug(f"{slug}: no Dropbox path available")
        return

    if not os.path.exists(path):
        debug(f"{slug}: expected output path does not exist: {path}")
        return

    debug(f"{slug}: opening Dropbox output path {path}")
    subprocess.Popen(["xdg-open", path])

def open_leanpub_error(slug, status_json):
    url = f"https://leanpub.com/author/book/{slug}/versions/error_details"
    
    debug(f"{slug}: opening Leanpub error page output path {url}")
    subprocess.Popen(["xdg-open", url])


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


def notify_with_action(slug, message, status_json, icon=None, actiontitle=None, actionfn=open_book_folder):
    if actiontitle:
        actionargs = ["-A", f"action={actiontitle}"]
    else:
        actionargs = []
    result = notify(slug, message, icon, actionargs)
    debug(f"Action selected = {result}")
    
    if result == "action":
        actionfn(slug, status_json)


def get_status(slug):
    url = f"https://leanpub.com/{slug}/job_status.json?api_key={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        debug_response(f"{slug} status", url, r)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        debug(f"{slug} status: request failed: {e}")
        return None


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
    global API_KEY
    global last_status
    global last_status_json
    global DEBUG
    global next_poll_at

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to JSON config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print API request and response debugging information to stderr.",
    )
    args = parser.parse_args()
    DEBUG = args.debug

    if os.path.exists(args.config):
        try:
            apply_config(load_config(args.config))
        except Exception as e:
            print(f"Error loading config from {args.config}: {e}", file=sys.stderr)
            sys.exit(1)

    env_api_key = os.environ.get("LEANPUB_API_KEY")
    if env_api_key:
        API_KEY = env_api_key
    if not API_KEY:
        print(
            "Missing Leanpub API key. Set LEANPUB_API_KEY or configure 'leanpub_api_key' in the config file.",
            file=sys.stderr,
        )
        sys.exit(1)

    debug("debug logging enabled")
    debug(f"config path = {args.config}")
    debug(f"books = {BOOKS}")
    debug(f"poll interval (POLL_INTERVAL) = {POLL_INTERVAL}")
    debug(f"active poll interval (ACTIVE_POLL_INTERVAL) = {ACTIVE_POLL_INTERVAL}")
    debug(f"notification timeout (NOTIFICATION_TIMEOUT_MS) = {NOTIFICATION_TIMEOUT_MS}")
    debug(f"dropbox type (DROPBOX_TYPE) = {DROPBOX_TYPE}")

    now = time.monotonic()
    next_poll_at = {slug: now for slug in BOOKS}

    while True:
        now = time.monotonic()
        for slug in BOOKS:
            due_at = next_poll_at.get(slug, now)
            if due_at > now:
                continue

            debug(f"--------- {slug} ---------")
            data = get_status(slug)
            if data is None:
                debug(f"{slug}: skipping status update because request failed")
                next_poll_at[slug] = now + POLL_INTERVAL
                continue
            state = interpret(data)
            prev = last_status.get(slug)
            prev_status_json = last_status_json.get(slug, {})
            if state == "unknown" and prev_status_json.get("status") == "complete":
                message = "Build finished successfully"
            else:
                message = format_status(data)
            debug(f"status message: {message}")

            # Avoid notifications on first run unless they are different from "unknown"
            if prev is None:
                prev = "unknown"

            if prev != message:
                icon = get_cover(slug)
                if state in {"complete", "unknown"}:
                    completion_status = dict(prev_status_json)
                    completion_status.update(data)
                    notify_with_action(slug, "Build finished successfully", completion_status, icon, "Reveal in Dropbox folder", open_book_folder)
                elif state in {"failed"}:
                    completion_status = dict(prev_status_json)
                    completion_status.update(data)
                    notify_with_action(slug, message, completion_status, icon, "Show error in Leanpub", open_leanpub_error)
                else:
                    notify(slug, message, icon)
                last_status[slug] = message
                last_status_json[slug] = data
            else:
                last_status_json[slug] = data

            if state == "working":
                next_poll_at[slug] = now + ACTIVE_POLL_INTERVAL
            else:
                next_poll_at[slug] = now + POLL_INTERVAL

        if not next_poll_at:
            time.sleep(POLL_INTERVAL)
            continue

        sleep_for = min(next_poll_at.values()) - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
