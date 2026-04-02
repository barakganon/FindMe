#!/usr/bin/env python3
"""
Run store geocoding. Requires GOOGLE_MAPS_API_KEY in .env for best results.

Usage:
    python -m db.run_geocoding              # geocode all ungeocoded stores
    python -m db.run_geocoding --force      # re-geocode all stores (improve accuracy)
    python -m db.run_geocoding --store-id UUID  # single store by UUID
    python -m db.run_geocoding --limit 100  # geocode up to 100 pending stores

Without GOOGLE_MAPS_API_KEY: uses Nominatim (limited — cannot handle Israeli mall names)
With GOOGLE_MAPS_API_KEY:    uses Google Maps (recommended — handles all Israeli addresses)

Add to .env:
    GOOGLE_MAPS_API_KEY=your_key_here
"""
from db.geocode_stores import main

if __name__ == "__main__":
    main()
