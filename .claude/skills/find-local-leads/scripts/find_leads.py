#!/usr/bin/env python3
"""Find local businesses that appear to have no website.

Sources:
  osm     OpenStreetMap via Overpass (free, no key; data can be incomplete)
  google  Google Places API (New) Text Search (needs GOOGLE_PLACES_API_KEY; most accurate)
  auto    google if the key is set, otherwise osm (default)

Writes a CSV of leads ranked by score, and prints a short summary.
Standard library only, so it runs anywhere with Python 3.8+.
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

USER_AGENT = "find-local-leads/1.0 (local business lead finder)"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

# Domains that are a profile page, not a real website. A business with only
# one of these is still a good lead.
SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "instagram.com", "yelp.com", "tiktok.com",
    "twitter.com", "x.com", "linktr.ee", "business.site", "google.com",
    "g.page", "doordash.com", "ubereats.com", "grubhub.com", "square.site",
    "booksy.com", "vagaro.com", "styleseat.com", "nextdoor.com",
)

# Category name -> (OSM filters as (tag key, allowed values), Google text query)
CATEGORIES = {
    "restaurant": ([("amenity", {"restaurant", "fast_food", "cafe"})], "restaurant"),
    "cafe": ([("amenity", {"cafe"})], "cafe"),
    "bakery": ([("shop", {"bakery"})], "bakery"),
    "barber": ([("shop", {"hairdresser"})], "barber shop"),
    "salon": ([("shop", {"hairdresser", "beauty", "cosmetics"})], "hair salon"),
    "nails": ([("shop", {"beauty"})], "nail salon"),
    "auto": ([("shop", {"car_repair", "tyres", "car"}), ("amenity", {"car_wash"})], "auto repair"),
    "retail": ([("shop", {"clothes", "shoes", "gift", "florist", "jewelry", "boutique",
                          "furniture", "hardware", "convenience"})], "local shop"),
    "fitness": ([("leisure", {"fitness_centre"})], "gym"),
    "trades": ([("craft", {"plumber", "electrician", "carpenter", "roofer", "painter", "hvac"})],
               "plumber electrician contractor"),
    "services": ([("shop", {"laundry", "dry_cleaning", "tailor", "tattoo", "pet_grooming"})],
                 "laundromat dry cleaner tailor"),
    "health": ([("amenity", {"dentist", "clinic", "veterinary"})], "dentist clinic"),
}
DEFAULT_CATEGORIES = ["restaurant", "barber", "salon", "auto", "retail", "services"]


def http_json(url, data=None, headers=None, timeout=90):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(location):
    q = urllib.parse.urlencode({"q": location, "format": "json", "limit": 1})
    results = http_json(f"{NOMINATIM_URL}?{q}")
    if not results:
        sys.exit(f"Could not find location: {location!r}. Try adding a city and state/country.")
    r = results[0]
    return float(r["lat"]), float(r["lon"]), r.get("display_name", location)


def is_social(url):
    host = urllib.parse.urlparse(url if "//" in url else "//" + url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)


def maps_search_url(name, address):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(f"{name} {address}".strip())


def score_lead(lead):
    """Higher = better lead: reachable, established, and clearly missing a site."""
    s = 0.0
    if lead["phone"]:
        s += 2
    if lead["address"]:
        s += 1
    if lead["social_only"]:
        s += 1  # active online but no real site: easy pitch
    reviews = lead.get("review_count") or 0
    rating = lead.get("rating") or 0
    if reviews:
        s += min(math.log10(reviews + 1) * 2, 6)  # popular businesses can afford it
    if rating >= 4.0:
        s += 1
    return round(s, 2)


# ---------- OpenStreetMap ----------

def overpass_query(lat, lon, radius, categories):
    parts = []
    for cat in categories:
        for key, values in CATEGORIES[cat][0]:
            regex = "|".join(sorted(values))
            for kind in ("node", "way"):
                parts.append(f'{kind}["name"]["{key}"~"^({regex})$"](around:{radius},{lat},{lon});')
    return f"[out:json][timeout:60];({''.join(parts)});out center tags;"


def run_overpass(query):
    last_err = None
    for url in OVERPASS_URLS:
        try:
            body = urllib.parse.urlencode({"data": query}).encode()
            return http_json(url, data=body)
        except Exception as e:  # try the next mirror
            last_err = e
            time.sleep(2)
    sys.exit(f"All Overpass servers failed ({last_err}). Try again in a minute, use a smaller --radius, or use --source google.")


def category_for_tags(tags, categories):
    for cat in categories:
        if any(tags.get(key) in values for key, values in CATEGORIES[cat][0]):
            return cat
    return categories[0]


def osm_address(tags):
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    city = tags.get("addr:city", "")
    return ", ".join(x for x in (street, city) if x)


def leads_from_osm(lat, lon, radius, categories):
    data = run_overpass(overpass_query(lat, lon, radius, categories))
    leads, seen = [], set()
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        sites = [tags.get(k) for k in ("website", "contact:website", "url", "brand:website") if tags.get(k)]
        socials = [tags.get(k) for k in ("contact:facebook", "facebook", "contact:instagram", "instagram") if tags.get(k)]
        real_sites = [s for s in sites if not is_social(s)]
        if real_sites or tags.get("brand") or tags.get("brand:wikidata"):
            continue  # has a site, or is a chain that has one
        address = osm_address(tags)
        key = (name.lower(), address.lower())
        if key in seen:
            continue
        seen.add(key)
        clat = el.get("lat") or el.get("center", {}).get("lat")
        clon = el.get("lon") or el.get("center", {}).get("lon")
        lead = {
            "name": name,
            "category": category_for_tags(tags, categories),
            "address": address,
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "rating": None,
            "review_count": None,
            "social_only": bool(sites or socials),
            "social_link": (sites + socials)[0] if (sites or socials) else "",
            "lat": clat,
            "lon": clon,
            "source": "osm",
            "source_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            "maps_url": maps_search_url(name, address),
            "verified": "",
        }
        lead["score"] = score_lead(lead)
        leads.append(lead)
    return leads


# ---------- Google Places ----------

PLACES_FIELDS = ",".join(f"places.{f}" for f in (
    "id", "displayName", "formattedAddress", "nationalPhoneNumber", "websiteUri",
    "rating", "userRatingCount", "primaryType", "googleMapsUri", "businessStatus", "location",
)) + ",nextPageToken"


def leads_from_google(lat, lon, radius, categories, key, max_pages=3):
    leads, seen = [], set()
    for cat in categories:
        token = None
        for _ in range(max_pages):
            body = {
                "textQuery": CATEGORIES[cat][1],
                "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(min(radius, 50000))}},
                "pageSize": 20,
            }
            if token:
                body["pageToken"] = token
            data = http_json(PLACES_URL, data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": PLACES_FIELDS,
            })
            for p in data.get("places", []):
                if p["id"] in seen or p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                    continue
                seen.add(p["id"])
                site = p.get("websiteUri", "")
                if site and not is_social(site):
                    continue
                name = p.get("displayName", {}).get("text", "")
                lead = {
                    "name": name,
                    "category": cat,
                    "address": p.get("formattedAddress", ""),
                    "phone": p.get("nationalPhoneNumber", ""),
                    "rating": p.get("rating"),
                    "review_count": p.get("userRatingCount"),
                    "social_only": bool(site),
                    "social_link": site,
                    "lat": p.get("location", {}).get("latitude"),
                    "lon": p.get("location", {}).get("longitude"),
                    "source": "google",
                    "source_url": p.get("googleMapsUri", ""),
                    "maps_url": p.get("googleMapsUri") or maps_search_url(name, p.get("formattedAddress", "")),
                    "verified": "yes (Google lists no website)",
                }
                lead["score"] = score_lead(lead)
                leads.append(lead)
            token = data.get("nextPageToken")
            if not token:
                break
            time.sleep(2)  # page tokens take a moment to become valid
    return leads


COLUMNS = ["score", "name", "category", "address", "phone", "rating", "review_count",
           "social_only", "social_link", "verified", "maps_url", "source", "source_url", "lat", "lon"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("location", help='Area to search, e.g. "Brooklyn, NY" or "78704"')
    ap.add_argument("--radius", type=int, default=2000, help="Search radius in meters (default 2000, about 1.2 miles)")
    ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES),
                    help=f"Comma list or 'all'. Options: {', '.join(CATEGORIES)}")
    ap.add_argument("--source", choices=["auto", "osm", "google"], default="auto")
    ap.add_argument("--out", default="leads.csv", help="CSV output path (default leads.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Keep only the top N leads (0 = all)")
    args = ap.parse_args()

    cats = list(CATEGORIES) if args.categories == "all" else [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        sys.exit(f"Unknown categories: {unknown}. Options: {', '.join(CATEGORIES)}")

    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    source = args.source if args.source != "auto" else ("google" if key else "osm")
    if source == "google" and not key:
        sys.exit("--source google needs the GOOGLE_PLACES_API_KEY environment variable.")

    lat, lon, place = geocode(args.location)
    print(f"Searching {args.radius} m around {place} ({lat:.5f}, {lon:.5f}) via {source}...", file=sys.stderr)

    leads = (leads_from_google(lat, lon, args.radius, cats, key) if source == "google"
             else leads_from_osm(lat, lon, args.radius, cats))
    leads.sort(key=lambda l: l["score"], reverse=True)
    if args.limit:
        leads = leads[:args.limit]

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(leads)

    print(f"Found {len(leads)} businesses with no website listed. Saved to {args.out}")
    for l in leads[:15]:
        extra = " (social page only)" if l["social_only"] else ""
        print(f"  [{l['score']:>5}] {l['name']} - {l['category']} - {l['address'] or 'no address'} - {l['phone'] or 'no phone'}{extra}")


if __name__ == "__main__":
    main()
