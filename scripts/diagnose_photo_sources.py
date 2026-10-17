#!/usr/bin/env python3
"""One-shot, bounded source health diagnostic for a publicly identified test ship.

No images are downloaded or stored, and no credentials are used. Only HTTP
response status, public identifiers, photo credits and thumbnail URL hosts
are printed. This is intentionally not part of the SDRCC runtime.
"""
from __future__ import annotations
import re
import time
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError
from core import traffic_voice_shipspotting as ship
from core import traffic_voice_debinnenvaart as binnen

MMSI = "244740814"
NAME = "INVOTIS VII"
IMO = "8354732"
ENI = "02334352"


def label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc + parsed.path + ("?" + parsed.query if parsed.query else "")


def host(url: str) -> str:
    return urlparse(url).netloc if url else ""


def check(name: str, url: str, fetch, cap: int):
    start = time.monotonic()
    try:
        body = fetch(url, cap)
        print(f"OK {name}: {label(url)}; seconds={time.monotonic()-start:.2f}; chars={len(body)}", flush=True)
        return body
    except HTTPError as exc:
        print(f"HTTP {name}: {label(url)}; status={exc.code}; seconds={time.monotonic()-start:.2f}", flush=True)
    except Exception as exc:
        print(f"ERROR {name}: {label(url)}; {type(exc).__name__}: {str(exc)[:160]}; seconds={time.monotonic()-start:.2f}", flush=True)
    return ""


def check_shipspotting():
    for route, key in (("/photos/gallery", "mmsi"), ("/photos/search", "mmsi"), ("/photos/search", "imo")):
        url = ship.BASE + route + "?" + urlencode({key: MMSI if key == "mmsi" else IMO, "sortBy": "newest", "viewType": "normal"})
        doc = check("shipspotting "+route+" "+key, url, ship._download, ship.MAX_SEARCH)
        if not doc:
            continue
        links, previews = ship._search_links(doc)
        print("  search: photo_links="+str(len(links))+" previews="+str(len(previews))+" has_search_form="+str("Photo Search" in doc)+" markers="+str([x for x in ("INVOTIS","8354732","244740814","/photos/") if x.lower() in doc.lower()]), flush=True)
        if links:
            print("  first photo path: "+label(links[0])+" preview_host="+host(previews.get(links[0],"")), flush=True)
    url = ship.BASE + "/photos/3672950"
    doc = check("shipspotting known verified photo", url, ship._download, ship.MAX_PHOTO)
    if doc:
        p = ship._Page()
        p.feed(doc)
        ids = ship._identifiers(p.words)
        credited = ship._credit(p.words)
        images = [ship._image_from_attrs(x) for x in p.images]
        metas = {key: host(p.meta.get(key,"")) for key in ("og:image","twitter:image")}
        print("  detail: identifiers="+str(ids)+" photographer="+str(credited)+" imgs="+str(len(p.images))+" valid_thumbnail_count="+str(sum(bool(x) for x in images))+" first_image_hosts="+str(list(dict.fromkeys(host(x.get("src","")) for x in p.images))[:8])+" meta_hosts="+str(metas), flush=True)
        decision = ship._detail(doc,url,"",MMSI,NAME,IMO,ENI,time.time())
        print("  detail parser result="+str(bool(decision))+" source="+str((decision or {}).get("source"))+" image_host="+host((decision or {}).get("image_url","")), flush=True)


def check_binnenvaart():
    urls = [binnen.BASE + "/schip_detail/invotis-vii/",
            binnen.BASE + "/schepen_a_z/?sort=i"]
    for url in urls:
        doc = check("debinnenvaart", url, binnen._fetch, binnen.MAX_DETAIL if "ship_detail" in url else binnen.MAX_INDEX)
        if not doc:
            continue
        if "ship_detail" in url:
            page = binnen._ShipDetail()
            page.feed(doc)
            print("  profile: headings="+str(page.headings[:3])+" photos="+str(len(page.images))+" credited_photos="+str(sum(bool(x[1]) for x in page.images))+" image_hosts="+str(list(dict.fromkeys(host(x[0]) for x in page.images))[:8]),flush=True)
            for supplied_eni in (ENI, ""):
                matched = binnen._parse_detail(doc,NAME,supplied_eni,url,MMSI,IMO,time.time(),require_current_name=not bool(supplied_eni))
                print("  parser eni="+str(bool(supplied_eni))+" accepted="+str(bool(matched))+" artist="+str((matched or {}).get("artist","")),flush=True)
        else:
            p=binnen._AlphabetIndex();p.feed(doc)
            print("  alphabet index rows="+str(len(p.rows))+" exact_name="+str([item[:2] for item in p.rows if binnen._norm(item[0])==binnen._norm(NAME)][:5]),flush=True)


if __name__ == "__main__":
    check_shipspotting()
    check_binnenvaart()
    print("Diagnostic complete: read-only public data; no image copies.", flush=True)
