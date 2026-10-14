#!/usr/bin/env python3
"""Read-only live Shipspotting check. Does not download or save photos.

Defaults to the public THALASSA photo shown in the SDRCC v0.66.4 bug report.
Specify --imo/--eni/--mmsi/--name to inspect another known vessel.
"""
import argparse
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import traffic_voice_shipspotting as ship


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Shipspotting HTML gallery and photo parsing")
    parser.add_argument("--imo", default="6514819")
    parser.add_argument("--eni", default="02206019")
    parser.add_argument("--mmsi", default="000000000")
    parser.add_argument("--name", default="THALASSA")
    args = parser.parse_args()
    print("Shipspotting HTML gallery diagnostic (no images downloaded)")
    print("Vessel:", args.name, "| IMO:", args.imo, "| ENI:", args.eni)
    queries = []
    if args.imo:
        queries.append(("imo", args.imo))
    if args.eni:
        queries.append(("eni", args.eni.lstrip("0") or "0"))
    if not queries:
        queries.append(("mmsi", args.mmsi))
    for field, value in queries:
        url = ship.BASE + "/photos/gallery?" + urlencode({
            field: value, "sortBy": "newest", "viewType": "normal"
        })
        print("Gallery query:", field, value)
        try:
            html = ship._download(url, ship.MAX_SEARCH)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            print("Gallery unavailable:", type(exc).__name__, str(exc)[:160])
            continue
        links, previews = ship._search_links(html)
        print("Gallery HTML bytes:", len(html.encode("utf-8")))
        print("Photo links found:", len(links), "| thumbnail previews:", len(previews))
        for link in links[:3]:
            try:
                doc = ship._download(link, ship.MAX_PHOTO)
                page = ship._Page()
                page.feed(doc)
                identity = ship._identifiers(page.words)
                artist = ship._credit(page.words)
                result = ship._detail(doc, link, previews.get(link, ""),
                                      args.mmsi, args.name, args.imo, args.eni, 0)
                print("Photo:", link, "| IMO/MMSI/ENI:", identity,
                      "| photographer:", artist or "(not parsed)",
                      "| accepted:", bool(result))
                if result:
                    print("Thumbnail:", result["image_url"])
                    return
            except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
                print("Photo unavailable:", type(exc).__name__, str(exc)[:160])
    print("No accepted thumbnail. Other SDRCC photo sources still remain available.")


if __name__ == "__main__":
    main()
