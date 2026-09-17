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


def telegram(title, body, url, cfg):
    """Telegram bot. Better than ntfy if you already run one: real links, and
    the message survives in a chat you can scroll back through."""
    import requests
    token = cfg.get("telegram_token")
    chat_id = cfg.get("telegram_chat_id")
    if not token or not chat_id:
        raise RuntimeError("telegram_token / telegram_chat_id missing from watch-config.yaml")
    text = f"*{_md(title)}*\n{_md(body)}"
    if url:
        text += f"\n\n[Open]({url})"
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2",
              "disable_web_page_preview": False},
        timeout=10)
    if not r.ok:
        raise RuntimeError(f"telegram {r.status_code}: {r.text[:200]}")
    return True


_MD_ESCAPE = r"_*[]()~`>#+-=|{}.!"


def _md(s):
    """MarkdownV2 rejects unescaped punctuation, and deal titles are full of it."""
    return "".join("\\" + c if c in _MD_ESCAPE else c for c in str(s))


CHANNELS = {"console": console, "macos": macos, "ntfy": ntfy, "telegram": telegram}


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
