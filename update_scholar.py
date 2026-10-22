#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_scholar.py - Lấy dữ liệu từ hồ sơ Google Scholar và ghi ra scholar.json
(cạnh index.html). Trang web sẽ tự đọc file này.

Dữ liệu lấy về:
  - Số liệu tổng: citations, h_index, i10_index
  - Từng bài báo: title, authors, venue (tạp chí/hội nghị), year, citations, url

CÁCH DÙNG:
  pip install requests beautifulsoup4
  python update_scholar.py <GOOGLE_SCHOLAR_ID>
  (hoặc đặt biến môi trường GS_ID)

Cách 1 (mặc định): đọc trực tiếp trang Google Scholar (miễn phí, nhưng Google có thể
chặn nếu chạy từ máy chủ/GitHub Actions).
Cách 2 (ổn định hơn): đặt biến môi trường SERPAPI_KEY (https://serpapi.com, có gói
miễn phí) thì script dùng SerpAPI thay vì đọc trực tiếp.

Nếu lấy dữ liệu thất bại, script KHÔNG ghi đè scholar.json cũ và thoát với mã lỗi 1.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

# GS_ID = "CCCCCC"

BASE = "https://scholar.google.com"
PAGE_SIZE = 100
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scholar.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def to_int(text):
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else 0


# --------------------------------------------------------------------------
# Cách 1: đọc trực tiếp trang Google Scholar
# --------------------------------------------------------------------------
def fetch_direct(gs_id):
    from bs4 import BeautifulSoup  # import ở đây để cách 2 không cần bs4

    session = requests.Session()
    session.headers.update(HEADERS)
    stats = None
    pubs = []
    start = 0

    while True:
        params = {"user": gs_id, "hl": "en", "cstart": start, "pagesize": PAGE_SIZE}
        resp = session.get(BASE + "/citations", params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError("Google Scholar trả về HTTP %d" % resp.status_code)
        if "gs_captcha_f" in resp.text or "unusual traffic" in resp.text:
            raise RuntimeError(
                "Google Scholar yêu cầu CAPTCHA (đã chặn IP). "
                "Hãy chạy trên máy cá nhân hoặc dùng SERPAPI_KEY."
            )

        soup = BeautifulSoup(resp.text, "html.parser")

        if stats is None:
            cells = soup.select("#gsc_rsb_st td.gsc_rsb_std")
            if len(cells) < 6:
                raise RuntimeError("Không đọc được bảng chỉ số. Kiểm tra lại GS_ID.")
            stats = {
                "citations": to_int(cells[0].get_text()),
                "h_index": to_int(cells[2].get_text()),
                "i10_index": to_int(cells[4].get_text()),
            }

        rows = soup.select("tr.gsc_a_tr")
        for row in rows:
            link = row.select_one("a.gsc_a_at")
            if not link:
                continue
            grays = row.select("div.gs_gray")
            cite_el = row.select_one("td.gsc_a_c a")
            year_el = row.select_one("td.gsc_a_y span")
            pubs.append(
                {
                    "title": link.get_text(strip=True),
                    "authors": grays[0].get_text(strip=True) if len(grays) > 0 else "",
                    "venue": grays[1].get_text(strip=True) if len(grays) > 1 else "",
                    "year": to_int(year_el.get_text()) if year_el else 0,
                    "citations": to_int(cite_el.get_text()) if cite_el else 0,
                    "url": urljoin(BASE, link.get("href", "")),
                }
            )

        if len(rows) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        time.sleep(2)  # nghỉ giữa các trang để tránh bị chặn

    return stats, pubs


# --------------------------------------------------------------------------
# Cách 2: SerpAPI (ổn định hơn khi chạy trên máy chủ)
# --------------------------------------------------------------------------
def fetch_serpapi(gs_id, api_key):
    stats = None
    pubs = []
    start = 0

    while True:
        params = {
            "engine": "google_scholar_author",
            "author_id": gs_id,
            "hl": "en",
            "start": start,
            "num": PAGE_SIZE,
            "api_key": api_key,
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError("SerpAPI trả về HTTP %d: %s" % (resp.status_code, resp.text[:200]))
        data = resp.json()
        if data.get("error"):
            raise RuntimeError("SerpAPI lỗi: %s" % data["error"])

        if stats is None:
            table = (data.get("cited_by") or {}).get("table") or []
            try:
                stats = {
                    "citations": int(table[0]["citations"]["all"]),
                    "h_index": int(table[1]["h_index"]["all"]),
                    "i10_index": int(table[2]["i10_index"]["all"]),
                }
            except (IndexError, KeyError, TypeError, ValueError):
                raise RuntimeError("SerpAPI không trả về bảng chỉ số. Kiểm tra lại GS_ID.")

        articles = data.get("articles") or []
        for a in articles:
            cited = a.get("cited_by") or {}
            pubs.append(
                {
                    "title": (a.get("title") or "").strip(),
                    "authors": (a.get("authors") or "").strip(),
                    "venue": (a.get("publication") or "").strip(),
                    "year": to_int(str(a.get("year") or "")),
                    "citations": to_int(str(cited.get("value") or "")),
                    "url": a.get("link") or "",
                }
            )

        if len(articles) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    return stats, pubs


# --------------------------------------------------------------------------
def main():
    gs_id = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GS_ID", "")).strip()
    if not gs_id:
        print("Thiếu Google Scholar ID. Dùng: python update_scholar.py <GS_ID>", file=sys.stderr)
        return 1

    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    try:
        if api_key:
            print("Lấy dữ liệu qua SerpAPI...")
            stats, pubs = fetch_serpapi(gs_id, api_key)
        else:
            print("Lấy dữ liệu trực tiếp từ Google Scholar...")
            stats, pubs = fetch_direct(gs_id)
    except Exception as exc:  # noqa: BLE001
        print("LỖI: %s" % exc, file=sys.stderr)
        print("Giữ nguyên scholar.json cũ (nếu có).", file=sys.stderr)
        return 1

    if not pubs:
        print("LỖI: không lấy được bài báo nào, không ghi đè file cũ.", file=sys.stderr)
        return 1

    result = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "citations": stats["citations"],
        "h_index": stats["h_index"],
        "i10_index": stats["i10_index"],
        "publications": pubs,
    }

    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_FILE)  # ghi nguyên tử, tránh file hỏng giữa chừng

    print(
        "Xong: %d trích dẫn, h-index %d, i10-index %d, %d bài báo -> %s"
        % (stats["citations"], stats["h_index"], stats["i10_index"], len(pubs), OUT_FILE)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
