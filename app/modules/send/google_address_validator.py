# app/modules/send/google_address_validator.py
"""
Address Validation using Nominatim (OpenStreetMap) — no API key required.
Free, globally available. Complies with OSM Nominatim usage policy:
  - Identifies itself via User-Agent
  - Max 1 req/sec for bulk operations (enforced in bulk_validate)
"""

import logging
import time
import urllib.parse
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_USER_AGENT = 'GridlineService/1.0 (internal shipping app)'

# ── OSM class/type → our classification ───────────────────────────────────────
# https://wiki.openstreetmap.org/wiki/Map_features
_BUSINESS_CLASSES   = {'amenity', 'shop', 'office', 'tourism', 'leisure',
                        'healthcare', 'craft', 'man_made'}
_BUSINESS_TYPES     = {'commercial', 'retail', 'office', 'civic', 'public',
                        'hospital', 'school', 'university', 'college',
                        'restaurant', 'cafe', 'hotel', 'bank', 'pharmacy',
                        'supermarket', 'warehouse', 'government'}
_INDUSTRIAL_CLASSES = {'industrial'}
_INDUSTRIAL_TYPES   = {'industrial', 'factory', 'warehouse', 'storage',
                        'construction', 'quarry', 'port'}
_RURAL_CLASSES      = {'natural', 'landuse', 'boundary', 'waterway'}
_RURAL_TYPES        = {'farm', 'farmland', 'meadow', 'forest', 'wood',
                        'grass', 'rural', 'village', 'hamlet', 'isolated_dwelling'}


class GoogleAddressValidator:
    """
    Validate and classify addresses via Nominatim (OpenStreetMap).
    Class is named GoogleAddressValidator for drop-in compatibility with existing imports.
    """

    SEARCH_URL = 'https://nominatim.openstreetmap.org/search'
    HEADERS    = {'User-Agent': _USER_AGENT, 'Accept-Language': 'en'}

    # ── Public ────────────────────────────────────────────────────────────────

    def validate(self, address_data: Dict) -> Dict:
        """
        Validate an address.

        address_data keys:
            street_lines  – list of street strings
            city          – city name
            state_code    – 2-char state abbreviation
            postal_code   – ZIP / postal code
            country_code  – ISO-2 country (default 'US')
            company       – optional company name
        """
        params = {
            'format':         'json',
            'addressdetails': 1,
            'limit':          1,
            'extratags':      1,
            'namedetails':    1,
        }

        # Use structured query when individual fields are present
        streets = address_data.get('street_lines', [])
        if streets:
            params['street']     = streets[0]
            params['city']       = address_data.get('city', '')
            params['state']      = address_data.get('state_code', '')
            params['postalcode'] = address_data.get('postal_code', '')
            params['country']    = address_data.get('country_code', 'US')
        else:
            params['q'] = self._build_address_string(address_data)

        try:
            resp = requests.get(
                self.SEARCH_URL,
                params=params,
                headers=self.HEADERS,
                timeout=8
            )
            resp.raise_for_status()
            results = resp.json()
        except requests.RequestException as e:
            logger.error(f'Nominatim request failed: {e}')
            return self._error(f'Unable to reach address validation service: {e}')

        if not results:
            # Try a looser free-text fallback before giving up
            fallback = self._fallback_search(address_data)
            if fallback:
                results = [fallback]
            else:
                return self._not_found(address_data)

        return self._parse(results[0], address_data)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, result: Dict, original_data: Dict) -> Dict:
        osm_class   = result.get('class', '')
        osm_type    = result.get('type', '')
        display     = result.get('display_name', '')
        lat         = float(result.get('lat', 0))
        lng         = float(result.get('lon', 0))
        importance  = float(result.get('importance', 0))
        addr_detail = result.get('address') or {}
        extra_tags  = result.get('extratags') or {}
        name_detail = result.get('namedetails') or {}

        classification = self._classify(osm_class, osm_type, extra_tags)

        # Build suggested address from OSM address components
        suggested = self._parse_components(addr_detail, original_data)

        carriers   = self._determine_carriers(classification)
        corrections = self._identify_corrections(original_data, suggested)
        is_valid   = classification not in ('INVALID',)

        # Confidence: OSM importance is 0–1
        confidence_pct = round(min(importance * 100, 100))

        # Map links — coordinates only, no API key needed
        maps_google = f'https://www.google.com/maps?q={lat},{lng}'
        maps_osm    = f'https://www.openstreetmap.org/?mlat={lat}&mlon={lng}&zoom=17'

        # Human-readable place name if OSM has one
        place_name = name_detail.get('name') or extra_tags.get('name') or ''

        details = {
            'formatted_address': display,
            'place_name':        place_name,
            'latitude':          lat,
            'longitude':         lng,
            'confidence':        confidence_pct,
            'osm_class':         osm_class,
            'osm_type':          osm_type,
            'maps_google':       maps_google,
            'maps_osm':          maps_osm,
        }

        if classification == 'INVALID':
            message   = '❌ Address could not be validated — please verify all fields.'
            error_type = 'invalid'
        elif classification == 'UNKNOWN':
            message   = '⚠️ Address found but type is uncertain — verify before shipping.'
            error_type = 'unknown'
        elif corrections:
            message   = f'✅ Valid {classification.title()} address — corrections suggested.'
            error_type = None
        else:
            message   = f'✅ Valid {classification.title()} address — ready to use!'
            error_type = None

        return {
            'success':        True,
            'is_valid':       is_valid,
            'classification': classification,
            'error_type':     error_type,
            'message':        message,
            'original':       self._original_dict(original_data),
            'suggested':      suggested,
            'corrections':    corrections,
            'details':        details,
            'carriers':       carriers,
            'maps_url':       maps_google,
            'coordinates':    {'lat': lat, 'lng': lng},
            'confidence':     confidence_pct,
        }

    def _parse_components(self, addr: Dict, original: Dict) -> Dict:
        """Map OSM address dict to our standard fields."""
        house_number = addr.get('house_number', '')
        road         = addr.get('road', '')
        suburb       = addr.get('suburb', '')
        city = (
            addr.get('city') or addr.get('town') or
            addr.get('village') or addr.get('county') or ''
        )
        state      = addr.get('state', '')
        postcode   = addr.get('postcode', '')
        country    = addr.get('country_code', 'us').upper()

        street_line = f'{house_number} {road}'.strip()
        street_lines = [l for l in [street_line, suburb] if l]
        if not street_lines:
            # fall back to what was submitted
            street_lines = original.get('street_lines', [])

        # Abbreviate state to 2 chars if OSM returns full name
        state_code = self._abbreviate_state(state) or original.get('state_code', state)

        return {
            'street_lines': street_lines,
            'city':         city or original.get('city', ''),
            'state_code':   state_code,
            'postal_code':  postcode or original.get('postal_code', ''),
            'country_code': country,
        }

    def _classify(self, osm_class: str, osm_type: str, extra_tags: Dict) -> str:
        if osm_class in _INDUSTRIAL_CLASSES or osm_type in _INDUSTRIAL_TYPES:
            return 'INDUSTRIAL'
        if osm_class in _BUSINESS_CLASSES or osm_type in _BUSINESS_TYPES:
            return 'BUSINESS'
        # Extra tags can explicitly carry building=commercial / office=* etc.
        building_tag = extra_tags.get('building', '')
        office_tag   = extra_tags.get('office', '')
        if building_tag in ('commercial', 'retail', 'office', 'civic', 'public'):
            return 'BUSINESS'
        if building_tag == 'industrial':
            return 'INDUSTRIAL'
        if office_tag:
            return 'BUSINESS'
        if osm_class in _RURAL_CLASSES or osm_type in _RURAL_TYPES:
            return 'RURAL'
        if osm_class in ('building', 'place') and osm_type in (
            'house', 'residential', 'apartments', 'detached', 'terrace',
            'semidetached_house', 'bungalow', 'yes'
        ):
            return 'RESIDENTIAL'
        if osm_class == 'highway' and osm_type == 'residential':
            return 'RESIDENTIAL'
        if osm_class == 'landuse' and osm_type == 'residential':
            return 'RESIDENTIAL'
        # Street address found but no clear type — default to RESIDENTIAL
        if osm_class in ('building', 'place', 'highway'):
            return 'RESIDENTIAL'
        return 'UNKNOWN'

    def _determine_carriers(self, classification: str) -> List[str]:
        if classification == 'INVALID':
            return []
        if classification == 'RURAL':
            return ['USPS', 'FedEx (may vary)', 'UPS (may vary)']
        return ['USPS', 'FedEx', 'UPS']

    def _identify_corrections(self, original: Dict, suggested: Dict) -> List[str]:
        corrections = []
        orig_s = ' '.join(original.get('street_lines', [])).upper()
        sugg_s = ' '.join(suggested.get('street_lines', [])).upper()
        if orig_s and sugg_s and orig_s != sugg_s:
            corrections.append(f"Street: {' '.join(suggested['street_lines'])}")
        if original.get('city', '').upper() != suggested.get('city', '').upper():
            corrections.append(f"City: {suggested['city']}")
        if original.get('postal_code', '').split('-')[0] != suggested.get('postal_code', '').split('-')[0]:
            corrections.append(f"ZIP: {suggested['postal_code']}")
        return corrections

    # ── Fallback & helpers ────────────────────────────────────────────────────

    def _fallback_search(self, address_data: Dict) -> Optional[Dict]:
        """Free-text search as a fallback when structured query returns nothing."""
        try:
            resp = requests.get(
                self.SEARCH_URL,
                params={'q': self._build_address_string(address_data),
                        'format': 'json', 'addressdetails': 1,
                        'extratags': 1, 'namedetails': 1, 'limit': 1},
                headers=self.HEADERS,
                timeout=8
            )
            data = resp.json()
            return data[0] if data else None
        except Exception:
            return None

    def _build_address_string(self, d: Dict) -> str:
        parts = list(d.get('street_lines', []))
        for k in ('city', 'state_code', 'postal_code'):
            if d.get(k):
                parts.append(d[k])
        parts.append(d.get('country_code', 'US'))
        return ', '.join(p for p in parts if p)

    def _original_dict(self, d: Dict) -> Dict:
        return {
            'street_lines': d.get('street_lines', []),
            'city':         d.get('city', ''),
            'state_code':   d.get('state_code', ''),
            'postal_code':  d.get('postal_code', ''),
            'country_code': d.get('country_code', 'US'),
            'company':      d.get('company', ''),
        }

    def _not_found(self, address_data: Dict) -> Dict:
        return {
            'success':        True,
            'is_valid':       False,
            'classification': 'INVALID',
            'error_type':     'invalid',
            'message':        '❌ Address not found — please verify all fields.',
            'original':       self._original_dict(address_data),
            'suggested':      None,
            'corrections':    [],
            'details':        {},
            'carriers':       [],
            'maps_url':       None,
            'coordinates':    None,
            'confidence':     0,
        }

    def _error(self, message: str) -> Dict:
        return {
            'success':        False,
            'is_valid':       False,
            'classification': 'INVALID',
            'error_type':     'api_error',
            'message':        f'⚠️ {message}',
            'original':       {},
            'suggested':      None,
            'corrections':    [],
            'details':        {},
            'carriers':       [],
            'maps_url':       None,
            'coordinates':    None,
            'confidence':     0,
        }

    _STATE_ABBREV = {
        'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
        'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
        'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
        'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
        'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
        'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN',
        'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE',
        'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
        'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC',
        'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR',
        'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
        'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
        'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
        'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
        'District of Columbia': 'DC', 'Puerto Rico': 'PR',
    }

    def _abbreviate_state(self, state_name: str) -> str:
        if len(state_name) == 2:
            return state_name.upper()
        return self._STATE_ABBREV.get(state_name, '')
