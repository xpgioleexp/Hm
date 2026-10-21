---
name: find-local-leads
description: Find local businesses near a location that have no website (or only a Facebook/Instagram/Yelp page), verify them, and produce a ranked lead list for selling web design, logo animation, or other digital services. Use this whenever the user wants prospects, leads, or clients for a local web design / marketing hustle, asks "which shops near me don't have a website", wants to cold call or walk into local businesses, or mentions building demo sites for local shops, even if they never say the word "leads".
---

# Find Local Leads

The goal is a short, trustworthy list of real local businesses the user can walk into or call, each with a clear reason they need a website. A list of 10 verified leads beats 200 unchecked rows: the user's time on foot is the expensive part.

## 1. Get the inputs

You need:
- **Location**: a city, neighborhood, address, or ZIP. If the user says "near me", ask where they are.
- **Business types** (optional): defaults to restaurants, barbers, salons, auto shops, small retail, and services. Available categories: `restaurant, cafe, bakery, barber, salon, nails, auto, retail, fitness, trades, services, health`, or `all`.
- **Radius** (optional): default 2000 m (~1.2 miles), which is walkable for door-to-door. Use 3000–5000 m for driving or calling.

Don't interrogate. If you have a location, start.

## 2. Run the search script

```bash
python3 <skill-dir>/scripts/find_leads.py "Austin, TX" --radius 2000 --categories barber,restaurant,auto --out leads.csv
```

Data sources (`--source`):
- **google**: used automatically if `GOOGLE_PLACES_API_KEY` is set. Most accurate: Google knows which businesses list a website, plus ratings and review counts. Costs money past Google's free monthly credit, so mention that if the user asks about setting it up.
- **osm** (OpenStreetMap): the free default, no key needed. OpenStreetMap often *doesn't record* a website a business actually has, so these results **must be verified** (step 3).

The script drops businesses with a listed website and chain brands, keeps ones with only a social page (flagged `social_only`, a great pitch: "you're getting customers on Instagram, a site would capture the rest"), and ranks by a score favoring reachable, established businesses.

If the script fails (server busy, network blocked), retry once with a smaller radius. If it still fails, fall back to web search: search terms like `barber shop <area>` and check each result for a website yourself. Tell the user the list came from search, not the script.

## 3. Verify the top candidates

Take the top ~15–20 rows and check each one with web search (`"<business name>" <city>`). You are checking:
- **Do they actually have a website?** If a real site shows up, drop them, or keep them as "outdated site" only if it's clearly broken, ancient, or not mobile-friendly.
- **Are they still open?** Skip "permanently closed".
- **Any useful detail for the pitch**: good reviews, an active Instagram, online ordering through DoorDash only, etc.

Fill the `verified` column in the CSV (e.g. `no site found`, `has site: example.com`, `closed`, `facebook only`). Never present an unverified OSM row as a confirmed lead; say it's unverified if you didn't get to it.

## 4. Deliver the results

Save the final CSV in the user's working directory (e.g. `leads-<area>.csv`) so they can open it in Excel or Google Sheets. Then show a short ranked table in chat of the best verified leads:

| # | Business | Type | Address | Phone | Why it's a good lead |
|---|----------|------|---------|-------|----------------------|

End with:
- How many were found vs. verified vs. dropped (and why), so the user trusts the list.
- A suggestion to pick the top 3–5 and build each a demo site before visiting, and an offer to build the first one.
- Optionally, a walking route order if leads cluster in one area.

## Notes
- Don't scrape Google Maps pages directly: it breaks Google's terms and gets blocked. Use the Places API or web search.
- Only collect what's public business info (name, address, business phone). No personal details about owners.
- Outreach advice, if asked: visit in quiet hours (mid-afternoon for restaurants, weekday mornings for salons), be brief, show the demo on a phone.
