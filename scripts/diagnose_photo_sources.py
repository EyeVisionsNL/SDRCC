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
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


def check_new_site():
    from urllib.request import urlopen, Request
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = []
            self.links = []
            self.images = []
            self.headings = []
            self.title = ""
            self.in_title = False
        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag == "script" and d.get("src"): self.scripts.append(d["src"])
            if tag == "a" and d.get("href"): self.links.append(d["href"])
            if tag == "img": self.images.append({key: d.get(key, "") for key in ("src","alt","srcset")})
            if tag == "title": self.in_title = True
        def handle_endtag(self, tag):
            if tag == "title": self.in_title = False
        def handle_data(self, value):
            if self.in_title: self.title += value

    for url in ["https://debinnenvaart.nl/",
                "https://debinnenvaart.nl/schip/3233",
                "https://debinnenvaart.nl/schip/14304"]:
        started = time.monotonic()
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SDRCC-source-verification/1.0)"})
            with urlopen(request, timeout=8) as response:
                html = response.read(1500000).decode("utf-8", "replace")
                actual = response.geturl()
            parsed = Links();parsed.feed(html)
            print("NEW SITE "+url+" final="+actual+" size="+str(len(html))+" seconds="+str(round(time.monotonic()-started,2))+" title="+parsed.title[:120],flush=True)
            print("  scripts="+str(parsed.scripts[:15]),flush=True)
            print("  links="+str(parsed.links[:30]),flush=True)
            print("  images="+str(parsed.images[:4]),flush=True)
            print("  markers="+str([word for word in ("__NEXT_DATA__","_next/static","__nuxt","api/","zoeken","Invotis","EU nummer","Foto:","GROENENDAAL") if word.lower() in html.lower()]),flush=True)
            for match in list(re.finditer(r'(?i)(api/|fetch\\(|Invotis|zoek)',html))[:3]:
                print("  snippet="+re.sub(r"\\s+"," ",html[max(0,match.start()-80):match.end()+120])[:240],flush=True)
        except Exception as e:
            print("NEW SITE ERROR "+url+" "+type(e).__name__+": "+str(e)[:130]+" seconds="+str(round(time.monotonic()-started,2)),flush=True)


if __name__ == "__main__":
    check_shipspotting()
    check_binnenvaart()
    check_new_site()
    # Inspect only the public SPA bundle, not any photographs.
    try:
        from urllib.request import Request, urlopen
        asset = "https://debinnenvaart.nl/assets/index-tos2UP46.js"
        with urlopen(Request(asset, headers={"User-Agent":"Mozilla/5.0"}), timeout=12) as response:
            js = response.read(4000000).decode("utf-8","replace")
        print("SPA JS bytes="+str(len(js)),flush=True)
        needles = ("/api/","fetch(","axios","/schepen","/schip/","search_field","search_value","/search","/vessels","/ships","photo","/graphql")
        for term in needles:
            places=[m.start() for m in re.finditer(re.escape(term),js,re.I)][:5]
            print("  JS TERM "+term+" hits="+str(len(places)),flush=True)
            for at in places[:3]:
                print("    "+re.sub(r"\\s+"," ",js[max(at-130,0):at+180])[:310],flush=True)
    except Exception as e:
        print("SPA JS ERROR "+type(e).__name__+": "+str(e)[:160],flush=True)
    # Verify the public data interface referenced by the SPA itself.
    try:
        import json
        from urllib.request import Request, urlopen
        from urllib.parse import urlencode
        roots = [
            "https://debinnenvaart.nl/api/schepen/14304",
            "https://debinnenvaart.nl/api/schepen?" + urlencode({"zoek":"INVOTIS VII","limit":4}),
            "https://debinnenvaart.nl/api/schepen?" + urlencode({"q":"INVOTIS VII","limit":4}),
            "https://debinnenvaart.nl/api/schepen?" + urlencode({"naam":"INVOTIS VII","limit":4}),
        ]
        for url in roots:
            started=time.monotonic()
            try:
                with urlopen(Request(url,headers={"User-Agent":"SDRCC-photo-metadata-diagnostic/1.0","Accept":"application/json"}),timeout=8) as response:
                    status=response.status
                    raw=response.read(850000)
                obj=json.loads(raw)
                print("NEW API "+label(url)+" status="+str(status)+" bytes="+str(len(raw))+" secs="+str(round(time.monotonic()-started,2)),flush=True)
                if isinstance(obj,dict):
                    print("  keys="+str(list(obj.keys())[:25]),flush=True)
                    for key in ("data","schepen","resultaten","items"):
                        if isinstance(obj.get(key),list):
                            print("  "+key+" count="+str(len(obj[key]))+" first_rows="+str([{k:v for k,v in row.items() if k in ("id","naam","laatste_naam","eni","eu_nummer","imo","thumb","thumb_url")} for row in obj[key][:4] if isinstance(row,dict)]),flush=True)
                    if "/14304" in url:
                        print("  vessel fields="+str([(k,type(v).__name__,len(v) if isinstance(v,(list,dict)) else str(v)[:90]) for k,v in obj.items()][:55]),flush=True)
                else:
                    print("  response_type="+type(obj).__name__,flush=True)
            except Exception as exc:
                print("NEW API ERROR "+label(url)+" "+type(exc).__name__+": "+str(exc)[:130],flush=True)
        for key in ("A.schepen(", "schepen({", "schepen(new", "zoekterm", "zoektekst", "zoek:", "zoek="):
            places=[m.start() for m in re.finditer(re.escape(key),js,re.I)][:5]
            print("  JS CALL "+key+" count="+str(len(places)),flush=True)
            for at in places[:2]:
                print("    "+js[max(0,at-150):at+260][:410],flush=True)
    except Exception as exc:
        print("NEW API DIAG ERROR "+type(exc).__name__+": "+str(exc)[:130],flush=True)
    try:
        import json
        from urllib.request import Request, urlopen
        from urllib.parse import urlencode
        for ship_id in ("15560", "14304"):
            url = "https://debinnenvaart.nl/api/schepen/" + ship_id
            with urlopen(Request(url,headers={"User-Agent":"SDRCC-photo-metadata-diagnostic/1.0","Accept":"application/json"}),timeout=8) as response:
                data=json.load(response)
            print("SHIP JSON id="+ship_id+" name="+str(data.get("naam"))+" latest="+str(data.get("laatste_naam"))+" eni_first="+str(data.get("eu_nummer_eerste"))+" eni_last="+str(data.get("eu_nummer_laatste"))+" photo_count="+str(len(data.get("fotos") or [])),flush=True)
            for photo in (data.get("fotos") or [])[:3]:
                print("  photo fields="+str([(k, v if not isinstance(v,str) else v[:250]) for k,v in photo.items()]) if isinstance(photo,dict) else "  photo type="+type(photo).__name__,flush=True)
        for name in ("GROENENDAAL", "DEROVA", "KOSTRA 3"):
            url = "https://debinnenvaart.nl/api/schepen?" + urlencode({"q":name,"per_page":10})
            with urlopen(Request(url,headers={"User-Agent":"SDRCC-photo-metadata-diagnostic/1.0","Accept":"application/json"}),timeout=8) as response:
                found=json.load(response)
            print("SHIP SEARCH name="+name+" total="+str(found.get("totaal"))+" rows="+str([{k:row.get(k) for k in ("id","naam","laatste_naam","eu_nummer_eerste","eu_nummer_laatste","thumb")} for row in (found.get("data") or [])[:8]]),flush=True)
    except Exception as exc:
        print("SHIP JSON ERROR "+type(exc).__name__+": "+str(exc)[:160],flush=True)
    print("Diagnostic complete: read-only public data; no image copies.", flush=True)
