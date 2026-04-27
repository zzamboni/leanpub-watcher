# leanpub-watcher

Small Linux desktop watcher for Leanpub build jobs.

It polls the Leanpub API for a fixed list of books and sends a desktop notification whenever the reported build status changes. Notifications include the book title when available and try to use the cached Leanpub cover image as the notification icon.

## What It Does

- Polls Leanpub build status every 30 seconds
- Polls active builds more frequently without increasing the polling rate for idle books
- Watches a configurable list of Leanpub book slugs
- Sends notifications through `notify-send`
- Fetches and caches book metadata and cover images under `~/.cache/leanpub-covers`
- Resolves the local Dropbox root from `~/.dropbox/info.json`
- Opens the expected Dropbox output folder for completed builds from the final notification action
- Supports `--debug` to print redacted request/response diagnostics to stderr

## Requirements

- Linux desktop with `notify-send`
- Python 3
- The Python `requests` package
- A Leanpub API key exposed as `LEANPUB_API_KEY`
- A local Dropbox install with `~/.dropbox/info.json` available if you want the notification action to open synced output folders

## Configuration

The watcher reads configuration from a JSON file by default:

`~/.config/leanpub-watcher/config.json`

You can point it to a different file with `--config /path/to/config.json`.

- `books`
- `poll_interval`
- `active_poll_interval`
- `notification_timeout_ms`
- `dropbox_type`

The effective precedence is:

- built-in defaults
- config file
- command-line flags

## Setup

Install the Python dependency:

```bash
python -m pip install requests
```

Export your Leanpub API key:

```bash
export LEANPUB_API_KEY=your_api_key_here
```

Create a config file such as:

```json
{
  "books": [
    "learning-hammerspoon",
    "learning-cfengine",
    "emacs-org-leanpub"
  ],
  "poll_interval": 30,
  "active_poll_interval": 5,
  "notification_timeout_ms": 5000,
  "dropbox_type": "personal"
}
```

An example is included in [config.example.json](config.example.json).

## Usage

Run normally:

```bash
./leanpub_watcher.py
```

Run with debug logging:

```bash
./leanpub_watcher.py --debug
```

Run with a custom config file:

```bash
./leanpub_watcher.py --config /path/to/config.json
```

You can also invoke it with Python directly:

```bash
python leanpub_watcher.py
```

## How Status Changes Are Reported

The watcher suppresses notifications on the first polling cycle so it can establish a baseline. After that, it notifies only when the formatted status message changes for a given book.

Transient request failures such as missing network connectivity after suspend/resume are ignored. The watcher keeps the last known state and resumes polling silently once connectivity returns.

When a book is in Leanpub's `working` state, only that book is polled at the shorter `active_poll_interval`. Books that are idle, complete, failed, or temporarily unreachable continue using the normal `poll_interval`.

Examples:

- `3/10 Generating PDF`
- `Build finished successfully`
- `Build failed`

For completed builds, the notification includes an `open` action. If selected, the watcher uses `xdg-open` on the expected Leanpub Dropbox output directory:

- `<Dropbox>/<slug>-output/preview` for preview jobs
- `<Dropbox>/<slug>-output/published` for publish jobs

## Notes And Limitations

- This is designed for a Linux notification environment and is not cross-platform.
- If Leanpub metadata or cover downloads fail, notifications still work but may not include title/cover enhancements.
- Temporary network failures do not produce notifications.
- The Dropbox action depends on Leanpub's `job_type` field and your local Dropbox sync layout matching Leanpub's standard output folders.
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
