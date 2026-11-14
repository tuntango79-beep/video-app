#!/usr/bin/env python3
"""Fetch the myUpload video list (login via the site's Ory auth) and
regenerate videos.js for the app. Stdlib only. Credentials come from
the MYUPLOAD_EMAIL / MYUPLOAD_PASSWORD environment variables (GitHub
Actions secrets). The password is never printed."""

import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://myupload.us"
EMAIL = os.environ.get("MYUPLOAD_EMAIL", "")
PASSWORD = os.environ.get("MYUPLOAD_PASSWORD", "")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj)), cj


def fetch(opener, url, data=None, headers=None, method=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with opener.open(req, timeout=40) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, url, body
    except Exception as e:  # network hiccup etc.
        print(f"request error for {url}: {e}")
        return 0, url, ""


def login_api_token(opener):
    """Ory API login flow -> session_token (or None)."""
    status, _, body = fetch(opener, BASE + "/.ory/self-service/login/api",
                            headers={"Accept": "application/json"})
    if status != 200:
        print(f"login flow init failed: HTTP {status}")
        return None
    try:
        action = json.loads(body)["ui"]["action"]
    except Exception:
        print("login flow init: unexpected response shape")
        return None
    payload = json.dumps({"identifier": EMAIL, "password": PASSWORD,
                          "method": "password"}).encode()
    status, _, body = fetch(opener, action, data=payload,
                            headers={"Content-Type": "application/json",
                                     "Accept": "application/json"})
    if status != 200:
        print(f"API login failed: HTTP {status}")
        return None
    try:
        token = json.loads(body).get("session_token")
    except Exception:
        token = None
    print("API login:", "OK" if token else "no session_token in response")
    return token


def login_browser_cookies(opener):
    """Ory browser login flow -> session cookie in the jar (True/False)."""
    status, final_url, _ = fetch(opener, BASE + "/.ory/self-service/login/browser")
    m = re.search(r"flow=([0-9a-f-]{36})", final_url)
    if not m:
        print(f"browser flow: no flow id (final URL {final_url[:80]})")
        return False
    flow_id = m.group(1)
    status, _, body = fetch(
        opener, BASE + f"/.ory/self-service/login/flows?id={flow_id}",
        headers={"Accept": "application/json"})
    if status != 200:
        print(f"browser flow: flow fetch HTTP {status}")
        return False
    try:
        flow = json.loads(body)
        action = flow["ui"]["action"]
        csrf = ""
        for node in flow["ui"]["nodes"]:
            if node.get("attributes", {}).get("name") == "csrf_token":
                csrf = node["attributes"].get("value", "")
    except Exception:
        print("browser flow: unexpected flow shape")
        return False
    form = urllib.parse.urlencode({
        "identifier": EMAIL, "password": PASSWORD,
        "method": "password", "csrf_token": csrf}).encode()
    status, final_url, _ = fetch(
        opener, action, data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    ok = "dashboard" in final_url
    print(f"browser login: HTTP {status}, landed on {final_url[:80]}, "
          f"{'OK' if ok else 'not on dashboard'}")
    return ok


def parse_rows(html):
    """Return list of dicts for each video row found in the list HTML."""
    rows = []
    # Split the page into chunks, each starting at a video detail link.
    parts = re.split(r'href="/dashboard/video-streaming/videos/[0-9a-f-]{36}"', html)
    for chunk in parts[1:]:
        code_m = re.search(r'myupload\.us/v/([A-Za-z0-9]+)', chunk)
        if not code_m:
            continue
        dur_m = re.search(r'\b(\d{1,2}:\d{2}(?::\d{2})?)\b', chunk)
        dim_m = re.search(r'(\d{2,5})\s*[×x]\s*(\d{2,5})', chunk)
        size_m = re.search(r'(\d+(?:\.\d+)?)\s*(MB|GB|KB)', chunk)
        status_m = re.search(r'\b(ready|processing|uploading|failed|disabled)\b', chunk)
        size = ""
        if size_m:
            num, unit = size_m.group(1), size_m.group(2)
            if num.endswith(".0"):
                num = num[:-2]
            size = f"{num} {unit}"
        rows.append({
            "code": code_m.group(1),
            "duration": dur_m.group(1) if dur_m else "",
            "portrait": bool(dim_m and int(dim_m.group(2)) > int(dim_m.group(1))),
            "size": size,
            "status": status_m.group(1) if status_m else "",
        })
    return rows


def get_all_rows(opener, headers):
    all_rows, seen = [], set()
    for page in range(1, 21):
        url = BASE + f"/dashboard/video-streaming/videos?page={page}"
        status, _, html = fetch(opener, url, headers=headers)
        if status != 200:
            print(f"list page {page}: HTTP {status}")
            break
        rows = parse_rows(html)
        new = [r for r in rows if r["code"] not in seen]
        print(f"list page {page}: {len(rows)} rows, {len(new)} new")
        if page == 1 and not rows:
            print("page1 snippet:", re.sub(r"\s+", " ", html[:400]))
        for r in new:
            seen.add(r["code"])
            all_rows.append(r)
        if not new:
            break
    return all_rows


HEADER = """// ====== APP SETTINGS ======
window.APP_CONFIG = {
  appName: "Video App",
  ageGate: true
};

// ====== VIDEO LIST (auto-updated by the GitHub Actions program) ======
"""


def main():
    if not EMAIL or not PASSWORD:
        print("MYUPLOAD_EMAIL / MYUPLOAD_PASSWORD not set")
        return 1

    rows = []
    # Attempt 1: API token + bearer header.
    opener, _ = make_opener()
    token = login_api_token(opener)
    if token:
        rows = get_all_rows(opener, {"Authorization": f"Bearer {token}"})
    # Attempt 2: browser cookie login.
    if not rows:
        print("falling back to browser-cookie login")
        opener, _ = make_opener()
        if login_browser_cookies(opener):
            rows = get_all_rows(opener, {})
    if not rows:
        print("ERROR: could not read any video rows")
        return 1

    ready = [r for r in rows if r["status"] in ("", "ready")]
    print(f"total rows {len(rows)}, ready {len(ready)}")

    # Stable numbering: keep numbers already used in the current videos.js.
    existing = {}
    next_num = 1
    if os.path.exists("videos.js"):
        old = open("videos.js", encoding="utf-8").read()
        for m in re.finditer(
                r'title:\s*"Video (\d+)".{0,200}?embed:\s*"https://myupload\.us/embed/([A-Za-z0-9]+)"',
                old, re.S):
            existing[m.group(2)] = int(m.group(1))
        if existing:
            next_num = max(existing.values()) + 1

    # List pages are newest-first; assign new numbers oldest-first.
    numbered = []
    for r in reversed(ready):
        if r["code"] in existing:
            num = existing[r["code"]]
        else:
            num = next_num
            next_num += 1
        numbered.append((num, r))
    numbered.sort(key=lambda t: -t[0])  # newest (highest number) first

    blocks = []
    for num, r in numbered:
        lines = ["  {",
                 f'    title: "Video {num}",',
                 f'    embed: "https://myupload.us/embed/{r["code"]}",']
        if r["duration"]:
            lines.append(f'    duration: "{r["duration"]}",')
        if r["size"]:
            lines.append(f'    size: "{r["size"]}",')
        if r["portrait"]:
            lines.append("    portrait: true,")
        lines.append('    category: "New"')
        lines.append("  }")
        blocks.append("\n".join(lines))

    out = HEADER + "\nwindow.VIDEOS = [\n" + ",\n".join(blocks) + "\n];\n"
    with open("videos.js", "w", encoding="utf-8") as f:
        f.write(out)
    print(f"wrote videos.js with {len(blocks)} videos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
