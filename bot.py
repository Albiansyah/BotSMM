import asyncio
import logging
import config
import db
import sosmedly

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, PhotoSize,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


# ============ KONSTANTA ============
PLATFORMS = [
    ("instagram", "📸 Instagram"),
    ("tiktok", "🎵 TikTok"),
    ("youtube", "▶️ YouTube"),
    ("telegram", "✈️ Telegram"),
    ("twitter", "🐦 X / Twitter"),
    ("facebook", "📘 Facebook"),
    ("threads", "🧵 Threads"),
    ("linkedin", "💼 LinkedIn"),
    ("spotify", "🎧 Spotify"),
    ("shopee", "🛒 Shopee"),
    ("snackvideo", "🎬 Snack Video"),
    ("twitch", "🎮 Twitch"),
    ("roblox", "🎯 Roblox"),
    ("whatsapp", "💬 WhatsApp"),
]
PLATFORM_MAP = dict(PLATFORMS)

FINISHED_OK = {"completed", "partial"}
FINISHED_FAIL = {"canceled", "cancelled", "error", "fail", "failed", "refunded"}


def detect_platform(name: str) -> str:
    n = (name or "").lower()
    for key, _ in PLATFORMS:
        if key in n:
            return key
    return "lainnya"


def rupiah(n) -> str:
    try:
        return f"Rp{int(n):,}".replace(",", ".")
    except Exception:
        return f"Rp{n}"


# ============ STATES ============
class OrderFlow(StatesGroup):
    waiting_link = State()
    waiting_quantity = State()
    waiting_comments = State()


class TopUpFlow(StatesGroup):
    waiting_amount = State()
    waiting_proof = State()


class StatusFlow(StatesGroup):
    waiting_status_id = State()


class AdminFlow(StatesGroup):
    waiting_qris = State()


# ============ FORCE JOIN ============
async def is_subscribed(user_id: int) -> bool:
    if not config.FORCE_JOIN or not config.CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(config.CHANNEL_ID, user_id)
        return isinstance(member, (ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner))
    except Exception as e:
        logger.error(f"Cek subscription gagal {user_id}: {e}")
        return False


def join_channel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Join Channel", url=config.CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Saya Sudah Join", callback_data="check_join")],
    ])


async def send_join_prompt(target):
    text = (
        f"👋 <b>Selamat datang di {config.BRAND_NAME} Bot</b>\n\n"
        f"⚠️ <b>Wajib join channel dulu</b> untuk menggunakan bot ini.\n\n"
        f"1️⃣ Klik <b>📢 Join Channel</b>\n"
        f"2️⃣ Join channel\n"
        f"3️⃣ Klik <b>✅ Saya Sudah Join</b>"
    )
    if isinstance(target, Message):
        await target.answer(text, reply_markup=join_channel_kb(), parse_mode="HTML")
    else:
        try:
            await target.edit_text(text, reply_markup=join_channel_kb(), parse_mode="HTML")
        except Exception:
            await target.answer(text, reply_markup=join_channel_kb(), parse_mode="HTML")


# ============ UI ============
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Katalog Produk", callback_data="cat")],
        [InlineKeyboardButton(text="💰 Saldo Saya", callback_data="my_balance"),
         InlineKeyboardButton(text="💳 Top-up", callback_data="topup")],
        [InlineKeyboardButton(text="📜 Riwayat Order", callback_data="my_orders"),
         InlineKeyboardButton(text="🔍 Cek Status", callback_data="menu_status")],
        [InlineKeyboardButton(text="🎁 Referral & Komisi", callback_data="my_referral")],
    ])


def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")]
    ])


def cancel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]
    ])


def platforms_menu(groups):
    buttons = []
    row = []
    for key, label in PLATFORMS:
        count = len(groups.get(key, []))
        if count == 0:
            continue
        row.append(InlineKeyboardButton(text=f"{label} ({count})", callback_data=f"plat:{key}:0"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if groups.get("lainnya"):
        buttons.append([InlineKeyboardButton(
            text=f"📦 Lainnya ({len(groups['lainnya'])})", callback_data="plat:lainnya:0"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


PER_PAGE = 8


def services_menu(platform, services, page, prices):
    total = len(services)
    start = page * PER_PAGE
    end = start + PER_PAGE
    page_items = services[start:end]
    total_pages = (total + PER_PAGE - 1) // PER_PAGE

    buttons = []
    for s in page_items:
        sid = s.get("service")
        name = s.get("name", "?")
        short = name[:36] + "…" if len(name) > 36 else name
        price = prices.get(str(sid), "?")
        buttons.append([InlineKeyboardButton(
            text=f"{short} | {rupiah(price)}/1K",
            callback_data=f"svc:{sid}:{platform}:{page}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"plat:{platform}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if end < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"plat:{platform}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ Platform", callback_data="cat")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def service_detail_menu(sid, platform, page):
    if platform == "search":
        back = InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")
    else:
        back = InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"plat:{platform}:{page}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Order Sekarang", callback_data=f"ord:{sid}")],
        [back],
    ])


def format_service_detail(s, sell_price):
    lines = [
        f"<b>{s.get('name', '?')}</b>\n",
        f"🆔 ID: <code>{s.get('service')}</code>",
        f"💵 Harga jual: <b>{rupiah(sell_price)}</b> / 1000",
        f"📊 Min: <b>{s.get('min')}</b> | Max: <b>{s.get('max')}</b>",
    ]
    if s.get("refill"):
        lines.append("♻️ Refill: ✅")
    return "\n".join(lines)


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


# ============ CANCEL ============
@dp.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer("❌ Dibatalkan")
    await state.clear()
    try:
        await call.message.edit_text(
            "❌ <b>Dibatalkan.</b>\n\nKetik /start untuk membuka menu.",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
    except Exception:
        await call.message.answer("❌ <b>Dibatalkan.</b>", reply_markup=main_menu(), parse_mode="HTML")


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Dibatalkan.", reply_markup=main_menu())


# ============ CHECK JOIN ============
@dp.callback_query(F.data == "check_join")
async def cb_check_join(call: CallbackQuery):
    uid = call.from_user.id
    if await is_subscribed(uid):
        await call.answer("✅ Terima kasih sudah join!")
        user = await db.get_user(uid)
        if not user:
            await db.create_user(uid, call.from_user.username or "", call.from_user.full_name)
        saldo = await db.get_saldo(uid)
        try:
            await call.message.edit_text(
                f"✅ <b>Verifikasi berhasil!</b>\n\n"
                f"💰 Saldo: <b>{rupiah(saldo)}</b>\n"
                f"🆔 ID Anda: <code>{uid}</code>\n\n"
                f"Pilih menu:",
                reply_markup=main_menu(),
                parse_mode="HTML"
            )
        except Exception:
            await call.message.answer("✅ Verifikasi berhasil!", reply_markup=main_menu())
    else:
        await call.answer("❌ Kamu belum join channel. Silakan join dulu.", show_alert=True)


# ============ START (dengan Referral) ============
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    uid = message.from_user.id

    if not await is_subscribed(uid):
        await send_join_prompt(message)
        return

    # Handle referral payload: /start ref_123456
    referrer_id = 0
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            candidate = int(args[1].replace("ref_", "").strip())
            if candidate != uid and candidate > 0:
                referrer_id = candidate
        except ValueError:
            pass

    user = await db.get_user(uid)
    is_new = user is None
    if is_new:
        await db.create_user(uid, message.from_user.username or "", message.from_user.full_name, referrer_id)
        if referrer_id:
            # Notif ke referrer
            try:
                ref_user = await db.get_user(referrer_id)
                if ref_user:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 <b>Referral Baru!</b>\n\n"
                        f"👤 {message.from_user.full_name} baru daftar pakai link kamu.\n"
                        f"💰 Kamu akan dapat komisi setiap dia top-up!",
                        parse_mode="HTML"
                    )
            except Exception:
                pass
    else:
        await db.update_user_info(uid, message.from_user.username or "", message.from_user.full_name)
        if referrer_id and not user.get("referrer_id"):
            await db.set_referrer(uid, referrer_id)

    if user and user.get("is_banned"):
        await message.answer("🚫 Akun Anda diblokir. Hubungi admin.")
        return

    saldo = await db.get_saldo(uid)
    await message.answer(
        f"👋 <b>Selamat datang di {config.BRAND_NAME} Bot</b>\n\n"
        f"Bot jual layanan sosial media termurah & terpercaya.\n\n"
        f"💰 Saldo: <b>{rupiah(saldo)}</b>\n"
        f"🆔 ID Anda: <code>{uid}</code>\n\n"
        f"Pilih menu di bawah ini:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    saldo = await db.get_saldo(call.from_user.id)
    try:
        await call.message.edit_text(
            f"🏠 <b>Menu Utama</b>\n\n💰 Saldo: <b>{rupiah(saldo)}</b>",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ============ KATALOG ============
@dp.message(Command("katalog"))
async def cmd_katalog(message: Message):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    await _show_katalog(message.answer)


@dp.callback_query(F.data == "cat")
async def cb_catalog(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    await _show_katalog(call.message.edit_text)


async def _show_katalog(send_func):
    try:
        await send_func("⏳ Mengambil katalog...")
    except Exception:
        pass
    services = await sosmedly.get_services()
    if not services:
        try:
            await send_func("❌ Katalog kosong. Cek API key di .env")
        except Exception:
            pass
        return
    groups = {}
    for s in services:
        p = detect_platform(s.get("name", ""))
        groups.setdefault(p, []).append(s)
    text = (
        f"🛍️ <b>Katalog Produk</b>\n\n"
        f"Total: <b>{len(services)}</b> layanan.\n"
        f"Pilih platform:"
    )
    try:
        await send_func(text, reply_markup=platforms_menu(groups))
    except Exception:
        await send_func(text)


@dp.callback_query(F.data.startswith("plat:"))
async def show_platform(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    _, platform, page_str = call.data.split(":")
    page = int(page_str)
    services = await sosmedly.get_services()
    filtered = [s for s in services if detect_platform(s.get("name", "")) == platform]
    if not filtered:
        await call.message.edit_text("❌ Tidak ada layanan.", reply_markup=back_menu())
        return
    start = page * PER_PAGE
    page_items = filtered[start:start + PER_PAGE]
    prices = {}
    for s in page_items:
        prices[str(s.get("service"))] = await sosmedly.calculate_sell_price(s)
    label = PLATFORM_MAP.get(platform, "📦 Lainnya")
    total_pages = (len(filtered) + PER_PAGE - 1) // PER_PAGE
    text = (
        f"{label}\n\n"
        f"Total: <b>{len(filtered)}</b> layanan\n"
        f"Halaman <b>{page+1}</b>/{total_pages}\n\n"
        f"Klik layanan untuk detail:"
    )
    try:
        await call.message.edit_text(text, reply_markup=services_menu(platform, filtered, page, prices), parse_mode="HTML")
    except Exception as e:
        if "not modified" not in str(e).lower():
            await call.message.answer(text, reply_markup=services_menu(platform, filtered, page, prices), parse_mode="HTML")


@dp.callback_query(F.data.startswith("svc:"))
async def show_service(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    parts = call.data.split(":")
    sid, platform, page = parts[1], parts[2], int(parts[3])
    services = await sosmedly.get_services()
    service = next((s for s in services if str(s.get("service")) == sid), None)
    if not service:
        await call.message.edit_text("❌ Layanan tidak ditemukan.", reply_markup=back_menu())
        return
    sell = await sosmedly.calculate_sell_price(service)
    await call.message.edit_text(
        format_service_detail(service, sell),
        reply_markup=service_detail_menu(sid, platform, page),
        parse_mode="HTML"
    )


# ============ SEARCH ============
@dp.message(Command("cari"))
async def cmd_cari(message: Message):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("🔍 Cara pakai: <code>/cari reels</code>", parse_mode="HTML")
        return
    keyword = parts[1].lower().strip()
    services = await sosmedly.get_services()
    matches = [s for s in services if keyword in (s.get("name") or "").lower()][:10]
    if not matches:
        await message.answer(f"❌ Tidak ada hasil untuk <b>{keyword}</b>.", parse_mode="HTML")
        return
    buttons = []
    for s in matches:
        sell = await sosmedly.calculate_sell_price(s)
        sid = s.get("service")
        name = (s.get("name") or "")[:36]
        buttons.append([InlineKeyboardButton(
            text=f"{name} | {rupiah(sell)}/1K", callback_data=f"svc:{sid}:search:0"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")])
    await message.answer(
        f"🔍 Hasil: <b>{keyword}</b> ({len(matches)} ditemukan)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


# ============ SALDO ============
@dp.message(Command("saldo"))
async def cmd_saldo(message: Message):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    saldo = await db.get_saldo(message.from_user.id)
    await message.answer(f"💰 <b>Saldo Anda</b>\n\n<b>{rupiah(saldo)}</b>", parse_mode="HTML", reply_markup=main_menu())


@dp.callback_query(F.data == "my_balance")
async def cb_my_balance(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    saldo = await db.get_saldo(call.from_user.id)
    try:
        await call.message.edit_text(
            f"💰 <b>Saldo Anda</b>\n\n<b>{rupiah(saldo)}</b>",
            parse_mode="HTML", reply_markup=main_menu()
        )
    except Exception:
        pass


# ============ REFERRAL ============
@dp.message(Command("referral"))
async def cmd_referral(message: Message):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    await _show_referral(message.answer, message.from_user.id)


@dp.callback_query(F.data == "my_referral")
async def cb_my_referral(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    await _show_referral(call.message.edit_text, call.from_user.id)


async def _show_referral(send_func, uid):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    stats = await db.get_referral_stats(uid)
    pct = await db.get_setting("referral_percent", "5")

    text = (
        f"🎁 <b>Program Referral</b>\n\n"
        f"Bagikan link ini ke teman-temanmu:\n"
        f"<code>{link}</code>\n\n"
        f"💰 Kamu dapat komisi <b>{pct}%</b> dari setiap top-up temanmu!\n"
        f"Komisi langsung masuk ke saldo kamu.\n\n"
        f"📊 <b>Statistik Kamu</b>\n"
        f"👥 Total diajak: <b>{stats['total_joined']}</b>\n"
        f"🔥 Yang top-up: <b>{stats['total_active']}</b>\n"
        f"💵 Total komisi: <b>{rupiah(stats['earned'])}</b>"
    )
    kbd = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Bagikan Link", url=f"https://t.me/share/url?url={link}&text=Gabung%20di%20{config.BRAND_NAME}!")],
        [InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")],
    ])
    try:
        await send_func(text, reply_markup=kbd)
    except Exception:
        await send_func(text)


@dp.message(Command("setrefpercent"))
async def cmd_setrefpercent(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        cur = await db.get_setting("referral_percent", "5")
        await message.answer(f"💰 Komisi referral saat ini: <b>{cur}%</b>\n\nGanti: <code>/setrefpercent 10</code>", parse_mode="HTML")
        return
    try:
        pct = float(parts[1])
    except ValueError:
        await message.answer("❌ Angka.")
        return
    if pct < 0 or pct > 100:
        await message.answer("❌ 0-100 saja.")
        return
    await db.set_setting("referral_percent", str(pct))
    await message.answer(f"✅ Komisi referral di-set <b>{pct}%</b>", parse_mode="HTML")


# ============ TOP-UP ============
@dp.message(Command("topup"))
async def cmd_topup(message: Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    await _start_topup(message.answer, state)


@dp.callback_query(F.data == "topup")
async def cb_topup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    await _start_topup(call.message.edit_text, state)


async def _start_topup(send_func, state):
    nominals = await db.get_setting("topup_nominals", "10000,25000,50000,100000,200000")
    amounts = [int(x) for x in nominals.split(",") if x.strip().isdigit()]
    buttons = []
    row = []
    for a in amounts:
        row.append(InlineKeyboardButton(text=rupiah(a), callback_data=f"tu_amt:{a}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ Nominal Lain", callback_data="tu_amt:custom")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")])
    await state.set_state(TopUpFlow.waiting_amount)
    try:
        await send_func(
            "💳 <b>Top-up Saldo</b>\n\nPilih nominal:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("tu_amt:"), StateFilter(TopUpFlow.waiting_amount))
async def cb_topup_amount(call: CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":")[1]
    if val == "custom":
        await call.message.edit_text(
            "✏️ Kirim nominal top-up (angka saja, min Rp10.000):",
            reply_markup=cancel_menu()
        )
        return
    await _show_qris(call.message, int(val), state)


@dp.message(TopUpFlow.waiting_amount)
async def topup_custom_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Kirim angka saja. Contoh: 50000", reply_markup=cancel_menu())
        return
    amt = int(message.text)
    if amt < 10000:
        await message.answer("❌ Minimal Rp10.000.", reply_markup=cancel_menu())
        return
    await _show_qris(message, amt, state)


async def _show_qris(message: Message, amount: int, state: FSMContext):
    qris_file_id = await db.get_setting("qris_file_id")
    qris_text = await db.get_setting("qris_text", "Scan QRIS di atas, atau transfer ke rekening yang tertera.")
    await state.update_data(topup_amount=amount)
    caption = (
        f"💳 <b>Top-up {rupiah(amount)}</b>\n\n"
        f"{qris_text}\n\n"
        f"Setelah transfer, kirim <b>foto bukti</b> ke sini."
    )
    kbd = cancel_menu()
    if qris_file_id:
        await message.answer_photo(qris_file_id, caption=caption, reply_markup=kbd, parse_mode="HTML")
    else:
        await message.answer(f"{caption}\n\n⚠️ Admin belum setup QRIS.", reply_markup=kbd, parse_mode="HTML")
    await state.set_state(TopUpFlow.waiting_proof)


@dp.message(TopUpFlow.waiting_proof, F.photo)
async def topup_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("topup_amount", 0)
    photo: PhotoSize = message.photo[-1]
    file_id = photo.file_id
    topup_id = await db.create_topup(message.from_user.id, amount, "QRIS", file_id)
    await state.clear()
    await message.answer(
        f"✅ Bukti diterima!\n\n"
        f"🆔 Top-up ID: <code>#{topup_id}</code>\n"
        f"💰 Nominal: <b>{rupiah(amount)}</b>\n\n"
        f"⏳ Menunggu approval admin.",
        parse_mode="HTML", reply_markup=back_menu()
    )
    uname = message.from_user.username or "-"
    fullname = message.from_user.full_name
    admin_text = (
        f"🔔 <b>TOP-UP BARU</b>\n\n"
        f"🆔 ID: <code>#{topup_id}</code>\n"
        f"👤 {fullname} (@{uname})\n"
        f"🆔 User ID: <code>{message.from_user.id}</code>\n"
        f"💰 <b>{rupiah(amount)}</b>"
    )
    kbd = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"tu_app:{topup_id}"),
         InlineKeyboardButton(text="❌ Reject", callback_data=f"tu_rej:{topup_id}")]
    ])
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, file_id, caption=admin_text, reply_markup=kbd, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Kirim notif admin {admin_id} gagal: {e}")


@dp.message(TopUpFlow.waiting_proof)
async def topup_proof_invalid(message: Message):
    await message.answer("❌ Kirim <b>foto</b> bukti transfer.", parse_mode="HTML", reply_markup=cancel_menu())


# ============ APPROVE TOP-UP + REFERRAL COMISSION ============
@dp.callback_query(F.data.startswith("tu_app:"))
async def cb_topup_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Bukan admin.", show_alert=True)
        return
    topup_id = int(call.data.split(":")[1])
    topup = await db.get_topup(topup_id)
    if not topup:
        await call.answer("Topup tidak ditemukan.", show_alert=True)
        return
    if topup["status"] != "pending":
        await call.answer(f"Sudah di-{topup['status']}.", show_alert=True)
        return

    await db.update_topup(topup_id, "approved", call.from_user.id)
    await db.add_saldo(topup["user_id"], topup["amount"])

    # Cek & bayar komisi referral
    user = await db.get_user(topup["user_id"])
    komisi_msg = ""
    if user and user.get("referrer_id"):
        ref_pct = float(await db.get_setting("referral_percent", "5") or 5)
        komisi = round(topup["amount"] * ref_pct / 100)
        if komisi > 0:
            await db.add_referral_earning(user["referrer_id"], komisi, user["telegram_id"], "topup")
            komisi_msg = f"\n\n🎁 Komisi referral <b>{rupiah(komisi)}</b> dikirim ke referrer."
            try:
                await bot.send_message(
                    user["referrer_id"],
                    f"🎁 <b>Komisi Referral Masuk!</b>\n\n"
                    f"👤 Dari: {user['full_name']}\n"
                    f"💰 Top-up: {rupiah(topup['amount'])}\n"
                    f"🎯 Komisi kamu ({ref_pct:.0f}%): <b>+{rupiah(komisi)}</b>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Notif referral gagal: {e}")

    # Tandai first topup
    if user and not user.get("first_topup_done"):
        await db.set_first_topup_done(user["telegram_id"])

    await call.message.edit_caption(
        caption=(call.message.caption or "") + f"\n\n✅ <b>APPROVED</b> by {call.from_user.full_name}{komisi_msg}",
        parse_mode="HTML"
    )
    await call.answer("✅ Approved")

    try:
        await bot.send_message(
            topup["user_id"],
            f"✅ <b>Top-up Disetujui!</b>\n\n"
            f"🆔 #{topup_id}\n"
            f"💰 +{rupiah(topup['amount'])}\n\n"
            f"Saldo sudah masuk. 🙏",
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("tu_rej:"))
async def cb_topup_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Bukan admin.", show_alert=True)
        return
    topup_id = int(call.data.split(":")[1])
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await call.answer("Tidak valid.", show_alert=True)
        return
    await db.update_topup(topup_id, "rejected", call.from_user.id)
    await call.message.edit_caption(
        caption=(call.message.caption or "") + f"\n\n❌ <b>REJECTED</b> by {call.from_user.full_name}",
        parse_mode="HTML"
    )
    await call.answer("❌ Rejected")
    try:
        await bot.send_message(
            topup["user_id"],
            f"❌ <b>Top-up Ditolak</b>\n\n🆔 #{topup_id}\n💰 {rupiah(topup['amount'])}",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ============ ORDER ============
@dp.callback_query(F.data.startswith("ord:"))
async def start_order_from_service(call: CallbackQuery, state: FSMContext):
    await call.answer()
    uid = call.from_user.id
    if not await is_subscribed(uid):
        await send_join_prompt(call.message)
        return
    user = await db.get_user(uid)
    if user and user.get("is_banned"):
        await call.answer("🚫 Akun diblokir.", show_alert=True)
        return
    _, sid = call.data.split(":")
    services = await sosmedly.get_services()
    service = next((s for s in services if str(s.get("service")) == sid), None)
    if not service:
        await call.message.edit_text("❌ Layanan tidak ditemukan.", reply_markup=back_menu())
        return
    sell_price = await sosmedly.calculate_sell_price(service)
    await state.update_data(
        service=sid, service_name=service.get("name"),
        service_min=int(service.get("min", 1)), service_max=int(service.get("max", 0)),
        service_price=sell_price, service_cost=float(service.get("rate", 0)),
    )
    await state.set_state(OrderFlow.waiting_link)
    await call.message.edit_text(
        f"🛒 <b>Order: {service.get('name')}</b>\n\n"
        f"💵 Harga: <b>{rupiah(sell_price)}</b> / 1000\n"
        f"📊 Min: {service.get('min')} | Max: {service.get('max')}\n\n"
        f"🔗 Kirim <b>link target</b>:",
        parse_mode="HTML", reply_markup=cancel_menu()
    )


@dp.message(OrderFlow.waiting_link)
async def order_link(message: Message, state: FSMContext):
    if not message.text or not message.text.strip():
        await message.answer("❌ Link kosong.", reply_markup=cancel_menu())
        return
    await state.update_data(link=message.text.strip())
    data = await state.get_data()
    await state.set_state(OrderFlow.waiting_quantity)
    await message.answer(
        f"🔢 Kirim <b>jumlah</b>\nMin: <b>{data.get('service_min')}</b> | Max: <b>{data.get('service_max')}</b>",
        parse_mode="HTML", reply_markup=cancel_menu()
    )


@dp.message(OrderFlow.waiting_quantity)
async def order_quantity(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Angka.", reply_markup=cancel_menu())
        return
    qty = int(message.text)
    data = await state.get_data()
    min_q = data.get("service_min", 1)
    max_q = data.get("service_max", 0)
    if qty < min_q:
        await message.answer(f"❌ Minimal {min_q}.", reply_markup=cancel_menu())
        return
    if max_q and qty > max_q:
        await message.answer(f"❌ Maksimal {max_q}.", reply_markup=cancel_menu())
        return
    total = round(data.get("service_price", 0) * qty / 1000)
    await state.update_data(quantity=qty, total_price=total)
    await state.set_state(OrderFlow.waiting_comments)
    await message.answer(
        f"💬 Kalau <b>Custom Comments</b>, kirim komentar (satu per baris).\n"
        f"Kalau bukan, kirim tanda <code>-</code>.\n\n"
        f"💰 Total: <b>{rupiah(total)}</b>",
        parse_mode="HTML", reply_markup=cancel_menu()
    )


@dp.message(OrderFlow.waiting_comments)
async def order_confirm(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Kirim teks atau -", reply_markup=cancel_menu())
        return
    comments = "" if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    await state.clear()
    uid = message.from_user.id
    total = data["total_price"]

    saldo = await db.get_saldo(uid)
    if saldo < total:
        await message.answer(
            f"❌ <b>Saldo kurang!</b>\n\n"
            f"💰 Saldo: {rupiah(saldo)}\n💸 Butuh: {rupiah(total)}\n"
            f"📉 Kurang: {rupiah(total - saldo)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Top-up", callback_data="topup")],
                [InlineKeyboardButton(text="🏠 Menu", callback_data="home")]
            ])
        )
        return

    await message.answer("⏳ Mengirim order...")
    result = await sosmedly.create_order(
        service=data["service"], link=data["link"],
        quantity=data["quantity"], comments=comments
    )
    if "error" in result:
        await message.answer(f"❌ Gagal: {result['error']}", reply_markup=back_menu())
        return
    provider_order_id = str(result.get("order", "-"))

    ok = await db.deduct_saldo(uid, total)
    if not ok:
        await message.answer("❌ Saldo tidak cukup (race). Coba lagi.", reply_markup=back_menu())
        return

    order_db_id = await db.create_order(
        user_id=uid, provider_order_id=provider_order_id,
        service_id=data["service"], service_name=data["service_name"],
        link=data["link"], quantity=data["quantity"],
        price_sell=total,
        price_cost=round(data.get("service_cost", 0) * data["quantity"] / 1000),
    )
    await db.inc_total_orders(uid, total)

    await message.answer(
        f"✅ <b>Order Berhasil!</b>\n\n"
        f"🆔 Order ID: <code>{order_db_id}</code>\n"
        f"🔖 Provider ID: <code>{provider_order_id}</code>\n"
        f"📦 {data['service_name']}\n"
        f"🔗 {data['link']}\n🔢 {data['quantity']}\n💸 {rupiah(total)}\n\n"
        f"Bot akan otomatis kirim notif kalau order selesai.",
        parse_mode="HTML", reply_markup=main_menu()
    )


# ============ RIWAYAT ============
@dp.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    orders = await db.get_user_orders(call.from_user.id, limit=10)
    if not orders:
        try:
            await call.message.edit_text("📜 Belum ada order.", reply_markup=back_menu())
        except Exception:
            pass
        return
    lines = ["📜 <b>Riwayat Order (10 terakhir)</b>\n"]
    for o in orders:
        emoji = "✅" if "complet" in (o["status"] or "").lower() else ("❌" if "cancel" in (o["status"] or "").lower() or "error" in (o["status"] or "").lower() else "⏳")
        lines.append(
            f"{emoji} #{o['id']} | <b>{o['status']}</b>\n"
            f"📦 {o['service_name'][:40]}\n"
            f"🔢 {o['quantity']} | 💸 {rupiah(o['price_sell'])}\n"
        )
    try:
        await call.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=back_menu())
    except Exception:
        await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=back_menu())


@dp.message(Command("riwayat"))
async def cmd_riwayat(message: Message):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    orders = await db.get_user_orders(message.from_user.id, limit=10)
    if not orders:
        await message.answer("📜 Belum ada order.", reply_markup=back_menu())
        return
    lines = ["📜 <b>Riwayat Order (10 terakhir)</b>\n"]
    for o in orders:
        lines.append(
            f"🆔 #{o['id']} | <b>{o['status']}</b>\n"
            f"📦 {o['service_name'][:40]}\n"
            f"🔢 {o['quantity']} | 💸 {rupiah(o['price_sell'])}\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=back_menu())


# ============ STATUS ============
@dp.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id):
        await send_join_prompt(message)
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(StatusFlow.waiting_status_id)
        await message.answer("🔍 Kirim <b>Order ID</b> (angka):", parse_mode="HTML", reply_markup=cancel_menu())
        return
    await _do_status(message, parts[1].strip(), state)


@dp.callback_query(F.data == "menu_status")
async def cb_status(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not await is_subscribed(call.from_user.id):
        await send_join_prompt(call.message)
        return
    await state.set_state(StatusFlow.waiting_status_id)
    try:
        await call.message.edit_text("🔍 Kirim <b>Order ID</b> (angka):", parse_mode="HTML", reply_markup=cancel_menu())
    except Exception:
        pass


@dp.message(StateFilter(StatusFlow.waiting_status_id), F.text)
async def handle_status_id(message: Message, state: FSMContext):
    await _do_status(message, message.text.strip(), state)


async def _do_status(message: Message, order_input: str, state: FSMContext):
    await state.clear()
    orders = await db.get_user_orders(message.from_user.id, limit=50)
    order = next((o for o in orders if str(o["id"]) == order_input or o["provider_order_id"] == order_input), None)
    if not order:
        await message.answer("❌ Order tidak ditemukan di riwayat Anda.", reply_markup=back_menu())
        return
    data = await sosmedly.get_status(order["provider_order_id"])
    provider_status = data.get("status", "-") if "error" not in data else order["status"]
    if "error" not in data:
        await db.update_order_status(order["id"], provider_status)
    refund_info = "\n💰 <i>Saldo sudah dikembalikan</i>" if order.get("refunded") else ""
    await message.answer(
        f"🔍 <b>Order #{order['id']}</b>\n\n"
        f"📦 {order['service_name']}\n🔗 {order['link']}\n🔢 {order['quantity']}\n💸 {rupiah(order['price_sell'])}\n\n"
        f"📊 Status: <b>{provider_status}</b>\n"
        f"▶️ Awal: {data.get('start_count', '-')}\n⏳ Sisa: {data.get('remains', '-')}{refund_info}",
        parse_mode="HTML", reply_markup=back_menu()
    )


# ============ BACKGROUND TASK (FITUR 1 & 2) ============
async def notif_order_complete(order, provider_data):
    try:
        await bot.send_message(
            order["user_id"],
            f"✅ <b>Order Selesai!</b>\n\n"
            f"🆔 Order ID: <code>{order['id']}</code>\n"
            f"📦 {order['service_name']}\n"
            f"🔗 {order['link']}\n"
            f"🔢 {order['quantity']}\n"
            f"💸 {rupiah(order['price_sell'])}\n\n"
            f"Terima kasih sudah order! 🙏",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Notif complete gagal: {e}")


async def refund_order(order):
    """Refund saldo user untuk order gagal."""
    try:
        await db.add_saldo(order["user_id"], order["price_sell"])
        # Kurangi total spent
        await bot.send_message(
            order["user_id"],
            f"💰 <b>Saldo Dikembalikan</b>\n\n"
            f"🆔 Order #{order['id']}\n"
            f"📦 {order['service_name']}\n"
            f"❌ Order gagal/dibatalkan\n"
            f"💵 Refund: <b>+{rupiah(order['price_sell'])}</b>\n\n"
            f"Saldo sudah masuk kembali ke akun kamu.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Refund gagal order #{order['id']}: {e}")


async def process_pending_orders():
    pending = await db.get_pending_orders(limit=config.ORDER_CHECK_BATCH)
    if not pending:
        return
    logger.info(f"[BG] Cek {len(pending)} order pending...")
    for o in pending:
        try:
            resp = await sosmedly.get_status(o["provider_order_id"])
            if "error" in resp:
                continue
            raw_status = (resp.get("status") or "").lower()
            old_status = (o["status"] or "").lower()

            # Update status di DB kalau beda
            if raw_status and raw_status != old_status:
                await db.update_order_status(o["id"], resp.get("status"))

            # Notif kalau order selesai
            if raw_status in FINISHED_OK and not o.get("notified"):
                await notif_order_complete(o, resp)
                await db.mark_order_notified(o["id"])

            # Refund kalau gagal
            elif raw_status in FINISHED_FAIL and not o.get("refunded"):
                await refund_order(o)
                await db.mark_order_refunded(o["id"])
                await db.mark_order_notified(o["id"])

        except Exception as e:
            logger.error(f"Loop order #{o['id']} error: {e}")
        await asyncio.sleep(1.2)  # hindari rate limit


async def background_loop():
    await asyncio.sleep(20)  # tunggu bot ready dulu
    while True:
        try:
            await process_pending_orders()
        except Exception as e:
            logger.error(f"Background loop error: {e}")
        await asyncio.sleep(config.ORDER_CHECK_INTERVAL)


# ============ ADMIN PANEL ============
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    total_users = await db.count_users()
    total_orders = await db.count_orders()
    rev, cost = await db.get_total_revenue()
    refund_count, refund_amount = await db.count_refunds()
    markup = await db.get_setting("markup_percent", "30")
    ref_pct = await db.get_setting("referral_percent", "5")
    try:
        sosmedly_bal = await sosmedly.get_balance()
        s_bal = sosmedly_bal.get("balance", "?")
    except Exception:
        s_bal = "?"
    await message.answer(
        f"⚙️ <b>Admin Panel</b>\n\n"
        f"👥 Users: <b>{total_users}</b>\n"
        f"🛒 Orders: <b>{total_orders}</b>\n"
        f"💰 Revenue: <b>{rupiah(rev)}</b>\n"
        f"💸 Cost: <b>{rupiah(cost)}</b>\n"
        f"📈 Profit: <b>{rupiah(rev - cost)}</b>\n"
        f"💔 Refund: <b>{refund_count}x</b> = {rupiah(refund_amount)}\n"
        f"📊 Markup: <b>{markup}%</b>\n"
        f"🎁 Referral: <b>{ref_pct}%</b>\n"
        f"💼 Saldo Sosmedly: <b>{s_bal}</b>\n\n"
        f"<b>Commands:</b>\n"
        f"/setmarkup [svc:&lt;id&gt;] &lt;persen&gt;\n"
        f"/resetmarkup svc:&lt;id&gt;\n"
        f"/setrefpercent &lt;persen&gt;\n"
        f"/addsaldo /cutsaldo &lt;uid&gt; &lt;jumlah&gt;\n"
        f"/ban /unban /user &lt;uid&gt;\n"
        f"/setqris /setqristext /setnominals\n"
        f"/broadcast &lt;pesan&gt;\n"
        f"/refresh — refresh cache\n"
        f"/checknow — paksa cek order sekarang",
        parse_mode="HTML"
    )


@dp.message(Command("checknow"))
async def cmd_checknow(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Memproses...")
    await process_pending_orders()
    await message.answer("✅ Selesai.")


@dp.message(Command("setmarkup"))
async def cmd_setmarkup(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        cur = await db.get_setting("markup_percent", "30")
        await message.answer(f"📊 Markup global: <b>{cur}%</b>", parse_mode="HTML")
        return
    if parts[1].startswith("svc:") and len(parts) >= 3:
        sid = parts[1].split(":", 1)[1]
        try:
            pct = float(parts[2])
        except ValueError:
            await message.answer("❌ Angka.")
            return
        await db.set_setting(f"markup_svc_{sid}", str(pct))
        await message.answer(f"✅ Markup svc <code>{sid}</code>: <b>{pct}%</b>", parse_mode="HTML")
        return
    try:
        pct = float(parts[1])
    except ValueError:
        await message.answer("❌ Angka.")
        return
    await db.set_setting("markup_percent", str(pct))
    await message.answer(f"✅ Markup global: <b>{pct}%</b>", parse_mode="HTML")


@dp.message(Command("resetmarkup"))
async def cmd_resetmarkup(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].startswith("svc:"):
        await message.answer("Gunakan: /resetmarkup svc:&lt;id&gt;", parse_mode="HTML")
        return
    sid = parts[1].split(":", 1)[1]
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as d:
        await d.execute("DELETE FROM settings WHERE key=?", (f"markup_svc_{sid}",))
        await d.commit()
    await message.answer(f"✅ Override svc <code>{sid}</code> dihapus.", parse_mode="HTML")


@dp.message(Command("addsaldo"))
async def cmd_addsaldo(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Gunakan: /addsaldo &lt;uid&gt; &lt;jumlah&gt;", parse_mode="HTML")
        return
    try:
        uid, amt = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("❌ Format salah.")
        return
    user = await db.get_user(uid)
    if not user:
        await message.answer("❌ User tidak ada.")
        return
    await db.add_saldo(uid, amt)
    await message.answer(f"✅ +{rupiah(amt)} ke <code>{uid}</code>", parse_mode="HTML")
    try:
        await bot.send_message(uid, f"🎁 Admin menambahkan saldo: <b>+{rupiah(amt)}</b>", parse_mode="HTML")
    except Exception:
        pass


@dp.message(Command("cutsaldo"))
async def cmd_cutsaldo(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Gunakan: /cutsaldo &lt;uid&gt; &lt;jumlah&gt;", parse_mode="HTML")
        return
    try:
        uid, amt = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("❌ Format salah.")
        return
    ok = await db.deduct_saldo(uid, amt)
    await message.answer("✅" if ok else "❌ Gagal (saldo kurang).")


@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.split()[1])
    except Exception:
        return
    await db.set_ban(uid, True)
    await message.answer(f"✅ User <code>{uid}</code> dibanned.", parse_mode="HTML")


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.split()[1])
    except Exception:
        return
    await db.set_ban(uid, False)
    await message.answer(f"✅ User <code>{uid}</code> di-unban.", parse_mode="HTML")


@dp.message(Command("user"))
async def cmd_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.split()[1])
    except Exception:
        return
    user = await db.get_user(uid)
    if not user:
        await message.answer("❌ Tidak ditemukan.")
        return
    stats = await db.get_referral_stats(uid)
    await message.answer(
        f"👤 <b>User Info</b>\n\n"
        f"🆔 <code>{user['telegram_id']}</code>\n"
        f"👤 {user['full_name']}\n"
        f"📛 @{user['username'] or '-'}\n"
        f"💰 Saldo: <b>{rupiah(user['saldo'])}</b>\n"
        f"📦 Total order: <b>{user['total_orders'] or 0}</b>\n"
        f"💵 Total spent: <b>{rupiah(user['total_spent'] or 0)}</b>\n"
        f"🎁 Referral: {stats['total_joined']} diajak / {rupiah(stats['earned'])} komisi\n"
        f"🚫 Banned: {'Ya' if user['is_banned'] else 'Tidak'}",
        parse_mode="HTML"
    )


@dp.message(Command("setqris"))
async def cmd_setqris(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminFlow.waiting_qris)
    await message.answer("📸 Kirim foto QRIS:", reply_markup=cancel_menu())


@dp.message(StateFilter(AdminFlow.waiting_qris), F.photo)
async def admin_qris_photo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    file_id = message.photo[-1].file_id
    await db.set_setting("qris_file_id", file_id)
    await state.clear()
    await message.answer("✅ QRIS disimpan.")


@dp.message(Command("setqristext"))
async def cmd_setqristext(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Gunakan: /setqristext Scan QRIS atau transfer ke BCA...")
        return
    await db.set_setting("qris_text", parts[1])
    await message.answer("✅ Teks QRIS disimpan.")


@dp.message(Command("setnominals"))
async def cmd_setnominals(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Gunakan: /setnominals 10000,25000,50000")
        return
    await db.set_setting("topup_nominals", parts[1])
    await message.answer("✅ Nominal disimpan.")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Gunakan: /broadcast &lt;pesan&gt;", parse_mode="HTML")
        return
    text = parts[1]
    ids = await db.get_all_user_ids()
    sent = 0
    for uid in ids:
        try:
            await bot.send_message(uid, f"📢 <b>Broadcast</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await message.answer(f"✅ Terkirim {sent}/{len(ids)}.")


@dp.message(Command("refresh"))
async def cmd_refresh(message: Message):
    if not is_admin(message.from_user.id):
        return
    sosmedly.clear_cache()
    await message.answer("✅ Cache di-refresh.")


# ============ FALLBACK ============
@dp.message()
async def fallback(message: Message):
    await message.answer("Gunakan /start untuk membuka menu.", reply_markup=main_menu())


# ============ STARTUP ============
async def main():
    await db.init_db()
    # Jalankan background task
    asyncio.create_task(background_loop())
    print(f"🤖 {config.BRAND_NAME} Bot berjalan...")
    print(f"🔄 Auto-notif & auto-refund: tiap {config.ORDER_CHECK_INTERVAL}s")
    if config.FORCE_JOIN:
        print(f"🔒 Wajib join channel ID: {config.CHANNEL_ID}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())