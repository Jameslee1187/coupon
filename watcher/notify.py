"""Alert delivery. ntfy for phone push, osascript for the Mac's own screen."""

import json
import subprocess


def console(title, body, url, cfg):
    print(f"\n*** {title}\n    {body}\n    {url or ''}")
    return True


def macos(title, body, url, cfg):
    """Native macOS banner. Local only - useless if you're away from the Mac."""
    script = (f'display notification {json.dumps(body)} '
              f'with title {json.dumps(title)} sound name "Glass"')
    subprocess.run(["osascript", "-e", script], check=False)
    return True


def ntfy(title, body, url, cfg):
    """Free push to your phone. Install the ntfy app, subscribe to your topic.

    The topic name is the only secret - anyone who knows it can read your
    alerts, so use something unguessable."""
    import requests
    topic = cfg.get("ntfy_topic")
    if not topic:
        raise RuntimeError("ntfy_topic missing from watch-config.yaml")
    server = cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title, "Priority": "high", "Tags": "moneybag"}
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open, {url}"
    r = requests.post(f"{server}/{topic}", data=body.encode("utf-8"),
                      headers=headers, timeout=10)
    r.raise_for_status()
    return True


CHANNELS = {"console": console, "macos": macos, "ntfy": ntfy}


def send(channels, title, body, url, cfg):
    ok = []
    for name in channels:
        fn = CHANNELS.get(name)
        if not fn:
            print(f"  ! unknown notify channel: {name}")
            continue
        try:
            fn(title, body, url, cfg)
            ok.append(name)
        except Exception as exc:
            print(f"  ! notify via {name} failed: {exc}")
    return ok
