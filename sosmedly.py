import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SOSMEDLY_API_KEY")
BASE_URL = os.getenv("SOSMEDLY_BASE_URL", "https://api.sosmedly.com/api/v2")

_lock = asyncio.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.05

_services_cache = None
_cache_time = 0.0
CACHE_TTL = 300


async def _request(action, **params):
    global _last_call
    async with _lock:
        now = asyncio.get_event_loop().time()
        wait = MIN_INTERVAL - (now - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)

        payload = {"key": API_KEY, "action": action, **params}

        async with aiohttp.ClientSession() as session:
            async with session.post(BASE_URL, data=payload, timeout=30) as resp:
                _last_call = asyncio.get_event_loop().time()

                if resp.status == 429:
                    retry = int(resp.headers.get("Retry-After", 60))
                    await asyncio.sleep(retry)
                    return {"error": f"Rate limit, coba lagi dalam {retry}s"}

                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return {"error": f"Response tidak valid (HTTP {resp.status})"}

                if isinstance(data, dict) and data.get("error"):
                    return {"error": str(data["error"])}

                return data


async def get_balance():
    return await _request("balance")


async def get_services(force=False):
    global _services_cache, _cache_time
    now = asyncio.get_event_loop().time()
    if not force and _services_cache and (now - _cache_time) < CACHE_TTL:
        return _services_cache

    data = await _request("services")
    if isinstance(data, dict):
        if data.get("error"):
            return []
        data = data.get("data", data.get("services", []))

    if not isinstance(data, list):
        return []

    _services_cache = data
    _cache_time = now
    return data


async def create_order(service, link, quantity, comments=""):
    params = {"service": service, "link": link, "quantity": quantity}
    if comments:
        params["comments"] = comments
    return await _request("add", **params)


async def get_status(order_id):
    return await _request("status", order=order_id)


def clear_cache():
    global _services_cache, _cache_time
    _services_cache = None
    _cache_time = 0.0


# ============ MARKUP ============
async def get_markup_percent(service_id=None) -> float:
    """Ambil markup dari DB. Bisa per-service, fallback ke global."""
    import db
    if service_id is not None:
        per_svc = await db.get_setting(f"markup_svc_{service_id}")
        if per_svc is not None:
            return float(per_svc)
    global_pct = await db.get_setting("markup_percent", "30")
    return float(global_pct or 30)


async def calculate_sell_price(service: dict) -> int:
    """Hitung harga jual dari harga provider + markup."""
    rate = float(service.get("rate", 0))
    pct = await get_markup_percent(service.get("service"))
    return round(rate * (1 + pct / 100))


async def get_markup_display(service_id=None) -> str:
    pct = await get_markup_percent(service_id)
    return f"{pct:.0f}%"