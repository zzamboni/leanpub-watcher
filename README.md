# leanpub-watcher

Small Linux desktop watcher for Leanpub build jobs.

It polls the Leanpub API for a fixed list of books and sends a desktop notification whenever the reported build status changes. Notifications include the book title when available and try to use the cached Leanpub cover image as the notification icon.

## What It Does

- Polls Leanpub build status every 30 seconds
- Watches a hard-coded list of book slugs in `leanpub_watcher.py`
- Sends notifications through `notify-send`
- Fetches and caches book metadata and cover images under `~/.cache/leanpub-covers`
- Supports `--debug` to print redacted request/response diagnostics to stderr

## Requirements

- Linux desktop with `notify-send`
- Python 3
- The Python `requests` package
- A Leanpub API key exposed as `LEANPUB_API_KEY`

The script also assumes your Leanpub-related Dropbox content lives under `~/Dropbox/Leanpub`, although that path is not part of the current command-line interface.

## Configuration

Configuration is currently done by editing `leanpub_watcher.py`:

- `BOOKS`: Leanpub book slugs to watch
- `POLL_INTERVAL`: polling interval in seconds
- `NOTIFICATION_TIMEOUT_MS`: notification display duration
- `DROPBOX_DIR`: base path used for local book folders
- `CACHE_DIR`: cache directory for metadata and cover images

## Setup

Install the Python dependency:

```bash
python -m pip install requests
```

Export your Leanpub API key:

```bash
export LEANPUB_API_KEY=your_api_key_here
```

Update the `BOOKS` list in `leanpub_watcher.py` to match the books you want to monitor.

## Usage

Run normally:

```bash
./leanpub_watcher.py
```

Run with debug logging:

```bash
./leanpub_watcher.py --debug
```

You can also invoke it with Python directly:

```bash
python leanpub_watcher.py
```

## How Status Changes Are Reported

The watcher suppresses notifications on the first polling cycle so it can establish a baseline. After that, it notifies only when the formatted status message changes for a given book.

Examples:

- `3/10 Generating PDF`
- `Build finished successfully`
- `Build failed`

## Notes And Limitations

- The watched books are hard-coded; there is no CLI or config file yet.
- This is designed for a Linux notification environment and is not cross-platform.
- If Leanpub metadata or cover downloads fail, notifications still work but may not include title/cover enhancements.
- The script runs indefinitely until stopped.

## Running As A User Service

If you want it to run in the background on login, a `systemd --user` service works well:

```ini
[Unit]
Description=Leanpub watcher

[Service]
ExecStart=/usr/bin/env python3 /absolute/path/to/leanpub_watcher.py
Environment=LEANPUB_API_KEY=your_api_key_here
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

Save that as `~/.config/systemd/user/leanpub-watcher.service`, then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now leanpub-watcher.service
```
