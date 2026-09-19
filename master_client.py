import aiohttp
import config

TIMEOUT = aiohttp.ClientTimeout(total=15)


def _is_enabled():
    return bool(config.MASTER_API_URL and config.TENANT_ID and config.MASTER_API_SECRET)


async def verify_tenant():
    """Cek tenant aktif & info fee."""
    if not _is_enabled():
        return {"ok": True, "skip": True}

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.post(
                f"{config.MASTER_API_URL}/api/verify",
                json={"tenant_id": config.TENANT_ID},
                headers={"X-API-Key": config.MASTER_API_SECRET},
            ) as r:
                return await r.json()
    except Exception as e:
        return {"ok": False, "reason": f"master_unreachable: {e}"}


async def deduct_fee(order_value: int, provider_order_id: str = ""):
    """Potong fee tenant untuk order ini."""
    if not _is_enabled():
        return {"ok": True, "skip": True}

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.post(
                f"{config.MASTER_API_URL}/api/deduct",
                json={
                    "tenant_id": config.TENANT_ID,
                    "order_value": order_value,
                    "provider_order_id": provider_order_id,
                },
                headers={"X-API-Key": config.MASTER_API_SECRET},
            ) as r:
                return await r.json()
    except Exception as e:
        return {"ok": False, "reason": f"master_unreachable: {e}"}