import logging
import re
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.assistant.prompts import get_prompt
from app.models.address import Address
from app.services.http_client import nominatim_verify_setting, requests_verify_setting
from app.utils.trace import trace, trace_async

logger = logging.getLogger(__name__)

NOMINATIM_USER_AGENT = "SignalSelectorTelecomApp/1.0 (contact: dev@prodapt.com)"
MAPBOX_FORWARD_GEOCODING_URL = "https://api.mapbox.com/search/geocode/v6/forward"


@trace
def clean_street_address(text: str, pincode: str | None = None) -> str:
    """Clean natural language conversational phrases and pincodes from address text."""
    if not text:
        return ""
    cleaned = text.strip()
    low = cleaned.lower()

    # 0. If text is a question/query without physical address keywords, return empty string
    if low.endswith("?") or re.search(r"\b(?:what|how|why|which|when|where|tell|show|can|could|would|provide|included)\b", low):
        if not re.search(r"\b(?:street|road|flat|apt|apartment|house|plot|building|lane|marg|nagar|society|colony|block|sector|floor)\b", low):
            return ""

    # 1. Remove 6-digit pincodes from the street address text
    cleaned = re.sub(r"\b[1-9][0-9]{5}\b", "", cleaned).strip()
    if pincode and pincode.strip() in cleaned:
        cleaned = cleaned.replace(pincode.strip(), "").strip()

    # 2. Strip conversational words/phrases anywhere in input
    conv_words = (
        r"\b(?:i|want|to|for|get|book|buy|order|need|new|connection|fiber|fibre|broadband|"
        r"service|area|available|in|okay|ok|yes|yeah|yep|sure|hi|hello|hey|my|your|here|is|this|"
        r"address|add|location|pincode|pin\s+code|zip\s+code|postal\s+code|check|serviceability|"
        r"coverage|live|at|located|discover|show|find|see|explore|plan|plans|options?|rates?|"
        r"tariffs?|packages?)\b"
    )
    cleaned = re.sub(conv_words, "", cleaned, flags=re.IGNORECASE).strip()

    # 3. Clean leading/trailing punctuation and extra whitespace
    cleaned = re.sub(r"^[,\s:-]+|[,\s:-]+$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 4. Check if remaining text has any real street/building indicators or numbers
    has_building_indicator = bool(re.search(r"\b(?:street|road|flat|apt|apartment|house|plot|building|lane|marg|nagar|society|colony|block|sector|floor|no|nr|near|opp|opposite|phase|stage|extension|ext|cross|main)\b", cleaned, re.I))
    has_number = bool(re.search(r"\d", cleaned))

    # If remaining text has no numbers, no building indicators, and is just generic words/too short, return empty
    if not has_building_indicator and not has_number and len(cleaned.split()) < 2:
        return ""

    if len(cleaned) < 3 or cleaned.lower() in {"india", "area", "city", "state", "town"}:
        return ""

    return cleaned



@trace
def extract_street_address_llm(text: str, pincode: str | None = None) -> str | None:
    """Use LLM to accurately extract physical street address (house/flat/building/street)
    from customer message, ignoring general intents, questions, and conversational text."""
    if not text or re.fullmatch(r"\d{6}", text.strip()):
        return None

    msg_clean = re.sub(r"\b[1-9][0-9]{5}\b", "", text).strip()
    if not msg_clean:
        return None

    try:
        from app.assistant.llm import generate_json
        prompt = get_prompt("address.street_extraction", text=text, pincode=pincode or "None")

        parsed = generate_json(prompt, system=get_prompt("address.street_extraction.system"), timeout=4)
        if parsed and isinstance(parsed, dict):
            if parsed.get("has_street_address") and parsed.get("street_address"):
                addr = str(parsed["street_address"]).strip()
                if len(addr) >= 3 and addr.lower() not in {"null", "none", "discover plans", "plans", "coverage", "check coverage"}:
                    return addr
            elif parsed.get("has_street_address") is False:
                return None
    except Exception as exc:
        logger.warning("LLM street address extraction failed, fallback to pattern cleaner: %s", exc)

    fallback_addr = clean_street_address(text, pincode)
    if fallback_addr.lower() in {"null", "none", "discover plans", "plans", "coverage", "check coverage"}:
        return None
    return fallback_addr or None


METRO_TELECOM_MAP = [
    (("delhi", "gurgaon", "gurugram", "noida", "ghaziabad", "faridabad", "ncr"), ("110", "122", "201"), "Delhi NCR"),
    (("mumbai", "navi mumbai", "thane", "pune", "kalyan"), ("400", "401", "402", "403", "404", "411"), "Mumbai"),
    (("bengaluru", "bangalore"), ("560", "561", "562"), "Bengaluru"),
    (("hyderabad", "secunderabad"), ("500", "501", "502"), "Hyderabad"),
    (("chennai",), ("600",), "Chennai"),
    (("kolkata", "calcutta", "howrah"), ("700", "711"), "Kolkata"),
]

STATE_TELECOM_MAP = [
    (("maharashtra", "goa"), "Maharashtra & Goa"),
    (("gujarat", "ahmedabad", "surat", "vadodara", "rajkot"), "Gujarat"),
    (("andhra", "telangana", "visakhapatnam", "vijayawada", "tirupati", "warangal"), "Andhra Pradesh & Telangana"),
    (("karnataka", "mysore", "mangalore", "hubli", "belgaum"), "Karnataka"),
    (("tamil nadu", "coimbatore", "madurai", "trichy", "salem", "tirupur"), "Tamil Nadu"),
    (("kerala", "kochi", "trivandrum", "thiruvananthapuram", "kozhikode", "thrissur"), "Kerala"),
    (("punjab", "haryana", "chandigarh", "amritsar", "ludhiana", "jalandhar", "panchkula"), "Punjab & Haryana"),
    (("up east", "lucknow", "kanpur", "varanasi", "allahabad", "prayagraj", "gorakhpur", "ayodhya"), "UP East"),
    (("up west", "uttar pradesh", "meerut", "agra", "bareilly", "aligarh", "mathura"), "UP West"),
    (("rajasthan", "jaipur", "udaipur", "jodhpur", "kota", "bikaner"), "Rajasthan"),
    (("west bengal", "sikkim", "siliguri", "gangtok", "darjeeling"), "West Bengal & Sikkim"),
    (("bihar", "jharkhand", "patna", "ranchi", "gaya", "jamshedpur", "dhanbad"), "Bihar & Jharkhand"),
    (("odisha", "orissa", "bhubaneswar", "cuttack", "puri", "rourkela"), "Odisha"),
    (("assam", "meghalaya", "manipur", "nagaland", "tripura", "mizoram", "arunachal", "guwahati", "shillong", "imphal"), "North East & Assam"),
    (("madhya pradesh", "chhattisgarh", "bhopal", "indore", "raipur", "gwalior", "jabalpur"), "MP & Chhattisgarh"),
]

PINCODE_PREFIX_MAP = [
    (("11", "12", "13", "14", "15", "16"), "Punjab & Haryana"),
    (("17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28"), "UP West"),
    (("30", "31", "32", "33", "34"), "Rajasthan"),
    (("36", "37", "38", "39"), "Gujarat"),
    (("40", "41", "42", "43", "44"), "Maharashtra & Goa"),
    (("45", "46", "47", "48", "49"), "MP & Chhattisgarh"),
    (("50", "51", "52", "53"), "Andhra Pradesh & Telangana"),
    (("56", "57", "58", "59"), "Karnataka"),
    (("60", "61", "62", "63", "64"), "Tamil Nadu"),
    (("67", "68", "69"), "Kerala"),
    (("70", "71", "72", "73", "74"), "West Bengal & Sikkim"),
    (("75", "76", "77"), "Odisha"),
    (("78", "79"), "North East & Assam"),
    (("80", "81", "82", "83", "84", "85"), "Bihar & Jharkhand"),
]


@trace
def get_telecom_circle(state: str = "", city: str = "", display_name: str = "", pincode: str = "") -> str:
    """Map detected Indian state, city, display_name, or pincode to exact Telecom Circle key using structured map tables."""
    loc_str = f"{city} {state} {display_name}".lower()
    pin = (pincode or "").strip()

    # 1. Metro Circles (Higher Priority)
    for keywords, pin_prefixes, circle in METRO_TELECOM_MAP:
        if any(k in loc_str for k in keywords) or pin.startswith(pin_prefixes):
            return circle

    # 2. Zonal/State Telecom Circles
    for keywords, circle in STATE_TELECOM_MAP:
        if any(k in loc_str for k in keywords):
            return circle

    # 3. Pincode Prefix Fallbacks
    for pin_prefixes, circle in PINCODE_PREFIX_MAP:
        if pin.startswith(pin_prefixes):
            return circle

    return "Delhi NCR"


def get_region_from_state(state: str, city: str = "", display_name: str = "", pincode: str = "") -> str:
    return get_telecom_circle(state=state, city=city, display_name=display_name, pincode=pincode)


def _verify_attempts(primary: bool | str) -> tuple[bool | str, ...]:
    """Try the configured TLS setting first, then one non-verified retry for local CA issues."""
    return (primary,) if primary is False else (primary, False)


@trace
def _normalize_mapbox_query(query: str) -> str:
    """Keep Mapbox forward-geocoding text within documented q limits."""
    cleaned = re.sub(r";+", " ", query or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    return " ".join(cleaned.split()[:20])[:256].strip(" ,")


@trace
def _context_name(context: dict | list | None, *keys: str) -> str | None:
    """Extract a named place from Mapbox v6 context, with tolerance for older list shapes."""
    if isinstance(context, dict):
        for key in keys:
            value = context.get(key)
            if isinstance(value, dict):
                name = value.get("name") or value.get("text")
                if name:
                    return str(name).strip()
            elif isinstance(value, str):
                return value.strip()
    elif isinstance(context, list):
        for key in keys:
            for item in context:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("feature_type") or "")
                if key in item_id:
                    name = item.get("text") or item.get("name")
                    if name:
                        return str(name).strip()
    return None


@trace
def _extract_pin_from_text(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b([1-9][0-9]{5})\b", str(value))
    return match.group(1) if match else None


@trace
def _mapbox_coordinates(feature: dict) -> tuple[float | None, float | None]:
    props = feature.get("properties") or {}
    prop_coords = props.get("coordinates") or {}
    lon = prop_coords.get("longitude")
    lat = prop_coords.get("latitude")
    if lat is not None and lon is not None:
        return lat, lon

    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) >= 2:
        return coords[1], coords[0]
    return None, None


@trace
def _mapbox_feature_to_geo(
    feature: dict,
    pincode: str,
    *,
    street_address: str | None = None,
    address_qualified: bool = False,
) -> dict | None:
    props = feature.get("properties") or {}
    context = props.get("context")
    name = props.get("full_address") or props.get("name_preferred") or props.get("name") or ""
    place_formatted = props.get("place_formatted") or ""
    display_name = props.get("full_address") or ", ".join(part for part in (name, place_formatted) if part)
    returned_pin = (
        _extract_pin_from_text(_context_name(context, "postcode"))
        or _extract_pin_from_text(props.get("postcode"))
        or _extract_pin_from_text(display_name)
    )

    if returned_pin and returned_pin != pincode.strip():
        input_zone = pincode.strip()[:2]
        returned_zone = returned_pin[:2]
        if input_zone != returned_zone:
            logger.warning(
                "Mapbox address/pincode mismatch: input=%s returned=%s for '%s'",
                pincode,
                returned_pin,
                street_address or pincode,
            )
            return None
        display_name = display_name.replace(returned_pin, pincode.strip())

    city = (
        _context_name(context, "place")
        or _context_name(context, "locality")
        or _context_name(context, "neighborhood")
        or _context_name(context, "district")
        or "Metro Center"
    )
    state = _context_name(context, "region") or "India"
    lat, lon = _mapbox_coordinates(feature)
    region = get_telecom_circle(state=state, city=city, display_name=display_name, pincode=pincode)

    if address_qualified:
        clean_street = street_address.strip().title() if street_address else ""
        formatted = display_name or f"{clean_street}, {city}, {state} {pincode.strip()}, India"
        if pincode.strip() not in formatted:
            formatted = f"{formatted}, {pincode.strip()}"
        return {
            "found": True,
            "serviceable": True,
            "address_qualified": True,
            "provider": "MAPBOX",
            "pincode": pincode,
            "street_address": street_address,
            "formatted_address": formatted,
            "city": city,
            "state": state,
            "region": region,
            "lat": lat,
            "lon": lon,
        }

    return {
        "found": True,
        "serviceable": True,
        "provider": "MAPBOX",
        "pincode": pincode,
        "city": city,
        "state": state,
        "region": region,
        "lat": lat,
        "lon": lon,
        "display_name": display_name or f"{city}, {state}, {pincode}",
    }


@trace
def _mapbox_forward_lookup(
    query: str,
    pincode: str,
    *,
    street_address: str | None = None,
    types: str | None = None,
    address_qualified: bool = False,
) -> dict | None:
    """Geocode address text using Mapbox Geocoding v6 forward endpoint."""
    settings = get_settings()
    token = settings.mapbox_token
    if not token:
        logger.info("MAPBOX_TOKEN is not configured; using geocoding fallback")
        return None

    normalized_query = _normalize_mapbox_query(query)
    if not normalized_query:
        return None

    params = {
        "q": normalized_query,
        "access_token": token,
        "country": "in",
        "worldview": "in",
        "language": "en",
        "autocomplete": "false",
        "limit": 1,
    }
    if types:
        params["types"] = types

    headers = {"User-Agent": NOMINATIM_USER_AGENT}
    for verify_ssl in _verify_attempts(requests_verify_setting()):
        try:
            res = requests.get(
                MAPBOX_FORWARD_GEOCODING_URL,
                params=params,
                headers=headers,
                timeout=4,
                verify=verify_ssl,
            )
            if res.status_code >= 400:
                logger.warning("Mapbox geocoding failed status=%s body=%s", res.status_code, res.text[:200])
                continue
            try:
                data = res.json()
            except ValueError as exc:
                logger.warning("Mapbox geocoding returned malformed JSON for %s: %s", normalized_query, exc)
                continue
            features = data.get("features") if isinstance(data, dict) else []
            if not features:
                logger.info("Mapbox geocoding returned no result for %s", normalized_query)
                continue
            geo = _mapbox_feature_to_geo(
                features[0],
                pincode,
                street_address=street_address,
                address_qualified=address_qualified,
            )
            if geo:
                logger.info("Mapbox geocoding successful for %s", normalized_query)
                return geo
        except Exception as exc:
            logger.warning("Mapbox geocoding attempt (verify=%s) failed for %s: %s", verify_ssl, normalized_query, exc)
    return None


@trace
def _mapbox_pincode_lookup(pincode: str) -> dict | None:
    """Geocode pincode using Mapbox as primary provider."""
    return _mapbox_forward_lookup(
        f"{pincode}, India",
        pincode,
        types="postcode,place,locality,district",
        address_qualified=False,
    )


@trace
def _extract_postal_code(components: list[dict]) -> str | None:
    for comp in components or []:
        if "postal_code" in (comp.get("types") or []):
            return (comp.get("short_name") or comp.get("long_name") or "").strip()
    return None


@trace
def _mapbox_address_lookup(street_address: str, pincode: str) -> dict | None:
    """Geocode full street address using Mapbox as primary provider."""
    return _mapbox_forward_lookup(
        f"{street_address}, {pincode}, India",
        pincode,
        street_address=street_address,
        types="address,street,postcode,place,locality,neighborhood",
        address_qualified=True,
    )


@trace
def _nominatim_pincode_lookup(pincode: str) -> dict | None:
    """Geocode pincode using Nominatim (OpenStreetMap) API fallback with custom User-Agent."""
    url = f"https://nominatim.openstreetmap.org/search?postalcode={pincode}&country=India&format=json&addressdetails=1"
    headers = {"User-Agent": NOMINATIM_USER_AGENT}
    for verify_ssl in _verify_attempts(nominatim_verify_setting()):
        try:
            res = requests.get(url, headers=headers, timeout=2, verify=verify_ssl)
            if res.status_code != 200:
                logger.warning("Nominatim pincode lookup status=%s for %s", res.status_code, pincode)
                continue
            try:
                payload = res.json()
            except ValueError as exc:
                logger.warning("Nominatim pincode lookup returned malformed JSON for %s: %s", pincode, exc)
                continue
            if payload:
                item = payload[0]
                addr = item.get("address", {})
                city = addr.get("city") or addr.get("state_district") or addr.get("county") or addr.get("town") or addr.get("suburb") or "Metro Center"
                state = addr.get("state") or "India"
                display_name = item.get("display_name", "")
                region = get_telecom_circle(state=state, city=city, display_name=display_name, pincode=pincode)
                return {
                    "found": True,
                    "serviceable": True,
                    "provider": "NOMINATIM",
                    "pincode": pincode,
                    "city": city,
                    "state": state,
                    "region": region,
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "display_name": display_name,
                }
        except Exception as exc:
            logger.warning("Nominatim pincode lookup attempt (verify=%s) failed for %s: %s", verify_ssl, pincode, exc)
    return None


@trace
def _nominatim_address_lookup(street_address: str, pincode: str) -> dict | None:
    """Geocode full street address using Nominatim (OpenStreetMap) API fallback with custom User-Agent."""
    query = f"{street_address}, {pincode}, India"
    url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&addressdetails=1"
    headers = {"User-Agent": NOMINATIM_USER_AGENT}
    for verify_ssl in _verify_attempts(nominatim_verify_setting()):
        try:
            res = requests.get(url, headers=headers, timeout=3, verify=verify_ssl)
            items = []
            if res.status_code == 200:
                try:
                    items = res.json() or []
                except ValueError as exc:
                    logger.warning("Nominatim address lookup returned malformed JSON for %s, %s: %s", street_address, pincode, exc)
            else:
                logger.warning("Nominatim address lookup status=%s for %s, %s", res.status_code, street_address, pincode)
            if not items:
                # Fallback to postalcode query if specific street building is not indexed in OSM
                url2 = f"https://nominatim.openstreetmap.org/search?postalcode={pincode}&country=India&format=json&addressdetails=1"
                res2 = requests.get(url2, headers=headers, timeout=3, verify=verify_ssl)
                if res2.status_code == 200:
                    try:
                        items = res2.json() or []
                    except ValueError as exc:
                        logger.warning("Nominatim postal fallback returned malformed JSON for %s: %s", pincode, exc)
                else:
                    logger.warning("Nominatim postal fallback status=%s for %s", res2.status_code, pincode)

            if items:
                item = items[0]
                addr = item.get("address", {})
                returned_pin = (addr.get("postcode") or "").strip()
                if returned_pin and returned_pin != pincode.strip():
                    input_zone = pincode.strip()[:2]
                    ret_zone = returned_pin[:2]
                    if input_zone != ret_zone:
                        logger.warning(
                            "Nominatim address/pincode mismatch: input=%s returned=%s for '%s' - rejecting as not legit",
                            pincode, returned_pin, street_address,
                        )
                        return None
                city = addr.get("city") or addr.get("state_district") or addr.get("county") or addr.get("town") or addr.get("suburb") or "Metro Center"
                state = addr.get("state") or "India"
                display_name = item.get("display_name", "")
                region = get_telecom_circle(state=state, city=city, display_name=display_name, pincode=pincode)

                clean_street = street_address.strip().title() if street_address else ""
                if clean_street and clean_street.lower() not in display_name.lower():
                    formatted = f"{clean_street}, {city}, {state} {pincode.strip()}, India"
                else:
                    formatted = display_name

                return {
                    "found": True,
                    "serviceable": True,
                    "address_qualified": True,
                    "provider": "NOMINATIM",
                    "pincode": pincode,
                    "street_address": street_address,
                    "formatted_address": formatted,
                    "city": city,
                    "state": state,
                    "region": region,
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                }
        except Exception as exc:
            logger.warning("Nominatim address lookup attempt (verify=%s) failed for %s, %s: %s", verify_ssl, street_address, pincode, exc)
    return None


@trace
def _is_invalid_or_dummy_pincode(pincode: str) -> bool:
    """Strictly identify non-existent, dummy, or invalid 6-digit Indian PIN codes.
    Returns False if input is not a 6-digit string (i.e. not intended as a 6-digit pincode).
    """
    pin = (pincode or "").strip()
    if len(pin) != 6 or not pin.isdigit():
        return False
    # 1. Invalid starting digits in India (Indian PIN codes start with digits 1 through 8 only)
    if pin.startswith(("0", "9")):
        return True
    # 2. Repeated digits (000000, 111111, 222222, 333333, 444444, 555555, 666666, 777777, 888888, 999999)
    if len(set(pin)) == 1:
        return True
    # 3. Known dummy / sequential pincodes
    if pin in {"123456", "654321", "234567", "345678", "456789", "567890", "987654"}:
        return True
    return False


@trace
def qualify(db: Session, pincode: str, street_address: str | None = None) -> dict:
    """Three-State Location Qualification using DB Serviceability Data + Mapbox / Nominatim:
    States:
    1. AVAILABLE (serviceable=True): Explicitly marked serviceable in DB or geocoded.
    2. UNAVAILABLE (serviceable=False): Explicitly marked unserviceable in DB.
    3. UNKNOWN (serviceable=True/pending): Valid pincode with no DB record - NOT automatically unserviceable.
    """
    cleaned_pin = (pincode or "").strip()
    if _is_invalid_or_dummy_pincode(cleaned_pin):
        return {
            "found": False,
            "serviceable": False,
            "serviceability_status": "INVALID",
            "address_qualified": False,
            "pincode": cleaned_pin,
            "message": f"Sorry, PIN code {cleaned_pin} is invalid. Valid Indian PIN codes are 6 digits starting with numbers 1 to 8."
        }

    # Query project's actual database serviceability record first
    db_addr = db.scalar(select(Address).where(Address.pincode == cleaned_pin))

    if db_addr and not db_addr.serviceable:
        # Explicitly marked UNAVAILABLE in DB
        return {
            "found": True,
            "serviceable": False,
            "serviceability_status": "UNAVAILABLE",
            "address_qualified": False,
            "pincode": cleaned_pin,
            "city": db_addr.city,
            "state": db_addr.state,
            "message": f"Sorry, our fiber services are currently unavailable at PIN code {cleaned_pin} in {db_addr.city}, {db_addr.state}. We are expanding soon!"
        }

    # Determine status & geocoding details
    serviceability_status = "AVAILABLE" if db_addr and db_addr.serviceable else "UNKNOWN"

    if street_address and street_address.strip():
        cleaned_street = clean_street_address(street_address, cleaned_pin) or street_address.strip()
        # Step 2B: Full Street Address Verification (Primary: Mapbox, Secondary: Nominatim, Fallback: DB)
        geo = _mapbox_address_lookup(cleaned_street, cleaned_pin) or _nominatim_address_lookup(cleaned_street, cleaned_pin)
        if not geo:
            if db_addr:
                region = get_telecom_circle(state=db_addr.state, city=db_addr.city, pincode=cleaned_pin)
                geo = {
                    "found": True,
                    "serviceable": True,
                    "serviceability_status": serviceability_status,
                    "address_qualified": True,
                    "provider": "TELECOM_CIRCLE_DB",
                    "pincode": cleaned_pin,
                    "street_address": cleaned_street,
                    "formatted_address": f"{cleaned_street}, {db_addr.city}, {db_addr.state} {cleaned_pin}",
                    "city": db_addr.city,
                    "state": db_addr.state,
                    "region": region,
                }
            else:
                region = get_telecom_circle(pincode=cleaned_pin)
                geo = {
                    "found": True,
                    "serviceable": True,
                    "serviceability_status": "UNKNOWN",
                    "address_qualified": True,
                    "provider": "PINCODE_REGION",
                    "pincode": cleaned_pin,
                    "street_address": cleaned_street,
                    "formatted_address": f"{cleaned_street}, {cleaned_pin}",
                    "city": "Metro Center",
                    "state": "India",
                    "region": region,
                }

        state_prefix = (geo.get("state") or "REG")[:3].upper()
        fdh_id = db_addr.fdh_id if db_addr else f"FDH-{state_prefix}-01"
        geo.update({
            "serviceability_status": serviceability_status,
            "fdh_id": fdh_id,
            "mst_id": db_addr.mst_id if db_addr else f"MST-{state_prefix}-01",
            "olt_id": db_addr.olt_id if db_addr else f"OLT-{state_prefix}-01",
            "max_speed_available_mbps": db_addr.max_speed_available_mbps if db_addr else 1000,
            "requires_full_address": False,
            "message": f"Address verified for {geo['city']}, {geo['state']} ({geo['region']} Circle). Regional plans unlocked!"
        })
        return geo

    # Pincode Only Check
    geo = _mapbox_pincode_lookup(cleaned_pin) or _nominatim_pincode_lookup(cleaned_pin)
    if not geo:
        if db_addr:
            region = get_telecom_circle(state=db_addr.state, city=db_addr.city, pincode=cleaned_pin)
            geo = {
                "found": True,
                "serviceable": True,
                "serviceability_status": serviceability_status,
                "pincode": cleaned_pin,
                "city": db_addr.city,
                "state": db_addr.state,
                "region": region,
                "fdh_id": db_addr.fdh_id,
            }
        else:
            region = get_telecom_circle(pincode=cleaned_pin)
            geo = {
                "found": True,
                "serviceable": True,
                "serviceability_status": "UNKNOWN",
                "pincode": cleaned_pin,
                "city": "Metro Center",
                "state": "India",
                "region": region,
                "fdh_id": "FDH-REG-01",
            }

    state_prefix = (geo.get("state") or "REG")[:3].upper()
    status_msg = (
        f"Pincode {cleaned_pin} in {geo.get('city', 'Metro')}, {geo.get('state', 'Zone')} is in our service area!"
        if serviceability_status == "AVAILABLE" else
        f"Pincode {cleaned_pin} in {geo.get('city', 'Metro')}, {geo.get('state', 'Zone')} is a valid area (coverage pending verification)."
    )
    geo.update({
        "serviceability_status": serviceability_status,
        "requires_full_address": True,
        "address_qualified": False,
        "fdh_id": db_addr.fdh_id if db_addr else f"FDH-{state_prefix}-01",
        "max_speed_available_mbps": db_addr.max_speed_available_mbps if db_addr else 1000,
        "message": f"{status_msg} Please share your complete street address (house/flat no, street, locality) to view regional fiber plans."
    })
    return geo


@trace
def select_service_address(db: Session, pincode: str, speed_mbps: int) -> dict:
    address = db.scalar(select(Address).where(Address.pincode == pincode, Address.serviceable.is_(True)))
    if address:
        if address.max_speed_available_mbps < speed_mbps:
            raise ValueError("Selected plan speed is not available at this address")
        return {"pincode": address.pincode, "city": address.city, "state": address.state,
                "fdh_id": address.fdh_id, "mst_id": address.mst_id, "olt_id": address.olt_id}
    
    # Fallback for dynamic Nominatim addresses
    state_prefix = "REG"
    return {"pincode": pincode, "city": "Metro Circle", "state": "Telecom Circle",
            "fdh_id": f"FDH-{state_prefix}-01", "mst_id": f"MST-{state_prefix}-01", "olt_id": f"OLT-{state_prefix}-01"}
