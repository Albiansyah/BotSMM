import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SOSMEDLY_API_KEY = os.getenv("SOSMEDLY_API_KEY", "")
SOSMEDLY_BASE_URL = os.getenv("SOSMEDLY_BASE_URL", "https://api.sosmedly.com/api/v2")

_raw = os.getenv("ADMIN_IDS", "").replace(" ", "")
ADMIN_IDS = [int(x) for x in _raw.split(",") if x.isdigit()]

BRAND_NAME = "SaldoNesia"
DEFAULT_MARKUP = 30

# ============ CHANNEL WAJIB JOIN ============
# CHANNEL_ID bisa berupa:
#   - Username channel publik: @saldonesia (string)
#   - ID numerik channel privat: -1001234567890 (integer)
_raw_channel = os.getenv("CHANNEL_ID", "").strip()
if not _raw_channel:
    CHANNEL_ID = 0
elif _raw_channel.startswith("@") or _raw_channel.startswith("https://"):
    CHANNEL_ID = _raw_channel  # biarkan string (username)
else:
    try:
        CHANNEL_ID = int(_raw_channel)
    except ValueError:
        CHANNEL_ID = _raw_channel  # fallback

CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/saldonesia")
FORCE_JOIN = os.getenv("FORCE_JOIN", "true").lower() == "true"

ORDER_CHECK_INTERVAL = int(os.getenv("ORDER_CHECK_INTERVAL", "300"))
ORDER_CHECK_BATCH = int(os.getenv("ORDER_CHECK_BATCH", "15"))

# ============ MASTER SYSTEM ============
MASTER_API_URL = os.getenv("MASTER_API_URL", "").rstrip("/")
MASTER_API_SECRET = os.getenv("MASTER_API_SECRET", "")
TENANT_ID = int(os.getenv("TENANT_ID", "0"))