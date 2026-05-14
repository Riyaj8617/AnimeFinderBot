"""
╔══════════════════════════════════════════════════════════════╗
║         RiyajMovieBot — Ultimate Edition V6.0                ║
║         Professional & Production Ready                      ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import re
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

import requests
import telebot
from telebot import types
from flask import Flask
from pymongo import MongoClient, ASCENDING, TEXT
from bson.objectid import ObjectId
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════
# 1. SETUP & CREDENTIALS
# ═══════════════════════════════════════════════════════
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")]
)
log = logging.getLogger(__name__)
log.info("🚀 RiyajMovieBot V6.0 Starting...")

BOT_TOKEN        = os.getenv("BOT_TOKEN")
TMDB_API_KEY     = os.getenv("TMDB_API_KEY")
MONGO_URI        = os.getenv("MONGO_URI")
MAIN_ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@YourChannel")
BOT_USERNAME     = os.getenv("BOT_USERNAME", "YourBot")

if not all([BOT_TOKEN, TMDB_API_KEY, MONGO_URI, MAIN_ADMIN_ID]):
    log.critical("❌ Please set all credentials in the .env file!")
    exit(1)

# ═══════════════════════════════════════════════════════
# 2. DATABASE
# ═══════════════════════════════════════════════════════
client       = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db           = client["RiyajMovieBot"]
files_col    = db["files"]
users_col    = db["users"]
searches_col = db["searches"]
settings_col = db["settings"]
requests_col = db["requests"]

def setup_indexes():
    try:
        files_col.create_index([("base_title", TEXT)])
        files_col.create_index([("file_id", ASCENDING)], unique=True)
        files_col.create_index([("base_title", ASCENDING), ("s_num", ASCENDING), ("quality", ASCENDING)])
        users_col.create_index([("user_id", ASCENDING)], unique=True)
        searches_col.create_index([("query", ASCENDING)], unique=True)
        log.info("✅ MongoDB indexes ready")
    except Exception as e:
        log.warning(f"Index: {e}")

# ═══════════════════════════════════════════════════════
# 3. BOT & FLASK
# ═══════════════════════════════════════════════════════
bot       = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
flask_app = Flask(__name__)
executor  = ThreadPoolExecutor(max_workers=20)

def get_settings() -> dict:
    s = settings_col.find_one({"id": "bot_settings"})
    if not s:
        s = {"id": "bot_settings", "auto_delete_min": 0, "admins": [MAIN_ADMIN_ID]}
        settings_col.insert_one(s)
    return s

# ═══════════════════════════════════════════════════════
# 4. SECURITY: ADMIN, RATE-LIMIT, CACHE
# ═══════════════════════════════════════════════════════
_rate_data: dict = defaultdict(list)
_sub_cache: dict = {}

def is_admin(user_id: int) -> bool:
    return user_id in get_settings().get("admins", [MAIN_ADMIN_ID])

def is_rate_limited(user_id: int) -> bool:
    if is_admin(user_id): return False
    now = time.time()
    _rate_data[user_id] = [t for t in _rate_data[user_id] if now - t < 10]
    if len(_rate_data[user_id]) >= 5: return True
    _rate_data[user_id].append(now)
    return False

def is_subscribed(user_id: int) -> bool:
    if is_admin(user_id): return True
    now = time.time()
    if user_id in _sub_cache and now - _sub_cache[user_id][1] < 300:
        return _sub_cache[user_id][0]
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        result = status in ("creator", "administrator", "member")
    except Exception:
        result = False
    _sub_cache[user_id] = (result, now)
    return result

def is_banned(user_id: int) -> bool:
    u = users_col.find_one({"user_id": user_id})
    return bool(u.get("banned", False)) if u else False

def clear_cache(user_id: int):
    _sub_cache.pop(user_id, None)

# ═══════════════════════════════════════════════════════
# 5. HELPERS
# ═══════════════════════════════════════════════════════
def get_deep_link(name: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={re.sub(r'[^a-zA-Z0-9]', '_', name)[:60]}"

def clean_name(text: str) -> str:
    text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    text = re.sub(r"@[a-zA-Z0-9_]+|https?://\S+", " ", text)
    junk = r"(?i)\b(1080p|720p|480p|360p|2160p|4k|hevc|10bit|amzn|web-?dl|bluray|brrip|dvdrip|hindi\s*audio|hindi\s*dub|dual\s*audio|esub|mkv|mp4|avi|full\s*movie)\b"
    text = re.sub(junk, " ", text)
    return re.sub(r"[^a-zA-Z0-9]", " ", text).strip().lower()

def extract_quality(text: str) -> str:
    """Always returns lowercase quality"""
    m = re.search(r"(?i)(2160p|4k|1080p|720p|480p|360p)", text)
    return m.group(1).lower() if m else "hd"

def delete_after(chat_id: int, msg_id: int, minutes: int):
    time.sleep(minutes * 60)
    try: bot.delete_message(chat_id, msg_id)
    except Exception: pass

def schedule_delete(chat_id: int, msg_id: int, minutes: int):
    if minutes > 0: executor.submit(delete_after, chat_id, msg_id, minutes)

def register_user(message):
    users_col.update_one(
        {"user_id": message.chat.id},
        {"$set": {
            "user_id":  message.chat.id,
            "username": message.from_user.username or "",
            "name":     f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        }},
        upsert=True
    )

def get_tmdb_info(query: str) -> tuple:
    try:
        res = requests.get(
            f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}",
            timeout=8
        ).json()
        if res.get("results"):
            item     = res["results"][0]
            title    = item.get("title") or item.get("name", query)
            is_movie = item.get("media_type") == "movie"
            poster   = f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else None
            rating   = round(item.get("vote_average", 0), 1)
            return title, poster, is_movie, rating
    except Exception as e:
        log.warning(f"TMDB: {e}")
    return query, None, True, 0

# ═══════════════════════════════════════════════════════
# 6. BOT MENUS
# ═══════════════════════════════════════════════════════
def set_bot_commands():
    try:
        bot.delete_my_commands(scope=types.BotCommandScopeDefault())
        user_cmds = [
            types.BotCommand("start",   "Start Bot 🚀"),
            types.BotCommand("list",    "All Collections 📚"),
            types.BotCommand("request", "Request Movie 🙋"),
        ]
        bot.set_my_commands(user_cmds, scope=types.BotCommandScopeDefault())
        admin_cmds = user_cmds + [
            types.BotCommand("stats",      "Dashboard 📊"),
            types.BotCommand("topsearch",  "Viral Searches 🔥"),
            types.BotCommand("pendingreq", "Pending Requests 📋"),
            types.BotCommand("settime",    "Auto-Delete ⏰"),
            types.BotCommand("rename",     "Rename Movies ✏️"),
            types.BotCommand("delete",     "Manage DB 🗑️"),
            types.BotCommand("post",       "Channel Post 🖼"),
            types.BotCommand("broadcast",  "Broadcast 📢"),
            types.BotCommand("ban",        "Ban User 🚫"),
            types.BotCommand("unban",      "Unban User ✅"),
            types.BotCommand("addadmin",   "Add Admin 👑"),
            types.BotCommand("rmadmin",    "Remove Admin ❌"),
        ]
        for admin_id in get_settings().get("admins", [MAIN_ADMIN_ID]):
            try:
                bot.delete_my_commands(scope=types.BotCommandScopeChat(admin_id))
                bot.set_my_commands(admin_cmds, scope=types.BotCommandScopeChat(admin_id))
            except Exception: pass
        log.info("✅ Menus updated")
    except Exception as e:
        log.error(f"Menu: {e}")

# ═══════════════════════════════════════════════════════
# 7. USER COMMANDS
# ═══════════════════════════════════════════════════════

@bot.message_handler(commands=["start"])
def cmd_start(message):
    register_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        message.text = parts[1].replace("_", " ")
        cmd_search(message)
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📚 Collections", callback_data="page|0"),
        types.InlineKeyboardButton("📢 Channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"),
    )
    bot.reply_to(message,
        "🎬 *Welcome to RiyajMovieBot!*\n\n"
        "Type the name of any movie, anime, or web series. 🍿",
        parse_mode="Markdown", reply_markup=markup
    )

@bot.message_handler(commands=["list"])
def cmd_list(message):
    if not is_subscribed(message.chat.id):
        return bot.reply_to(message, f"❌ Please join our channel first!\n👉 {CHANNEL_USERNAME}")
    send_list_page(message.chat.id, 0)

def send_list_page(chat_id: int, page: int, edit_msg_id: int = None):
    PAGE_SIZE = 15
    results = list(files_col.aggregate([
        {"$group": {"_id": "$base_title", "list_title": {"$first": "$list_title"}}},
        {"$sort": {"list_title": 1}},
        {"$skip": page * PAGE_SIZE},
        {"$limit": PAGE_SIZE + 1}
    ]))
    has_next = len(results) > PAGE_SIZE
    results  = results[:PAGE_SIZE]

    if not results:
        bot.send_message(chat_id, "🚫 No movies available yet.")
        return

    lines = [f"📚 *Collection* (Page {page + 1}):\n"]
    for r in results:
        title = r.get("list_title") or r["_id"].title()
        lines.append(f"🍿 [{title}]({get_deep_link(title)})")

    markup = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:    nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{page-1}"))
    if has_next:    nav.append(types.InlineKeyboardButton("➡️ Next", callback_data=f"page|{page+1}"))
    if nav: markup.add(*nav)

    text = "\n".join(lines)
    if edit_msg_id:
        try: bot.edit_message_text(text, chat_id, edit_msg_id, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
        except Exception: pass
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)

@bot.message_handler(commands=["request"])
def cmd_request(message):
    register_user(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, "📝 Usage: `/request Movie Name`", parse_mode="Markdown")
    title = parts[1].strip()

    if requests_col.find_one({"title_lower": title.lower(), "status": "pending"}):
        return bot.reply_to(message, f"✅ `{title}` is already requested!", parse_mode="Markdown")

    res = requests_col.insert_one({"user_id": message.chat.id, "username": message.from_user.username or "", "title": title, "title_lower": title.lower(), "status": "pending"})
    bot.reply_to(message, f"✅ Request sent successfully!\n🎬 *{title}*", parse_mode="Markdown")

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Approve", callback_data=f"reqok|{res.inserted_id}"),
        types.InlineKeyboardButton("❌ Reject",  callback_data=f"reqno|{res.inserted_id}")
    )
    for admin_id in get_settings().get("admins", [MAIN_ADMIN_ID]):
        try: bot.send_message(admin_id, f"🔔 *New Request!*\n🎬 `{title}`\n👤 User: `{message.chat.id}`", parse_mode="Markdown", reply_markup=markup)
        except Exception: pass

# ═══════════════════════════════════════════════════════
# 8. ADMIN COMMANDS
# ═══════════════════════════════════════════════════════

@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message.chat.id): return
    s = get_settings()
    timer   = f"{s.get('auto_delete_min',0)} mins" if s.get('auto_delete_min',0) > 0 else "Disabled"
    pending = requests_col.count_documents({"status": "pending"})
    bot.reply_to(message,
        f"📊 *Dashboard*\n\n"
        f"👥 Users: `{users_col.count_documents({})}`\n"
        f"🎬 Files: `{files_col.count_documents({})}`\n"
        f"🍿 Titles: `{len(files_col.distinct('base_title'))}`\n"
        f"🙋 Pending: `{pending}`\n"
        f"⏰ Auto-Delete: `{timer}`\n"
        f"👑 Admins: `{len(s.get('admins',[MAIN_ADMIN_ID]))}`",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["topsearch"])
def cmd_topsearch(message):
    if not is_admin(message.chat.id): return
    top = list(searches_col.find().sort("count", -1).limit(10))
    if not top: return bot.reply_to(message, "🚫 No search data available.")
    lines = ["🔥 *Trending Searches:*\n"]
    for i, s in enumerate(top, 1):
        lines.append(f"{i}. {s['query'].title()} — `{s['count']}` times")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["pendingreq"])
def cmd_pending_requests(message):
    if not is_admin(message.chat.id): return
    pending = list(requests_col.find({"status": "pending"}).sort("_id", -1).limit(10))
    if not pending: return bot.reply_to(message, "✅ No pending requests.")
    text   = "📋 *Pending Requests:*\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for r in pending:
        text += f"🎬 `{r['title']}` — `{r['user_id']}`\n"
        markup.add(
            types.InlineKeyboardButton(f"✅ {r['title'][:15]}", callback_data=f"reqok|{r['_id']}"),
            types.InlineKeyboardButton(f"❌ {r['title'][:15]}", callback_data=f"reqno|{r['_id']}")
        )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message.chat.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return bot.reply_to(message, "⚠️ Usage: `/settime <minutes>`", parse_mode="Markdown")
    mins = int(parts[1])
    settings_col.update_one({"id": "bot_settings"}, {"$set": {"auto_delete_min": mins}})
    bot.reply_to(message, f"✅ Auto-Delete set to `{mins}` mins." if mins > 0 else "❌ Auto-Delete disabled.", parse_mode="Markdown")

@bot.message_handler(commands=["addadmin"])
def cmd_addadmin(message):
    if message.chat.id != MAIN_ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Usage: `/addadmin UserID`", parse_mode="Markdown")
    new_admin = int(parts[1])
    settings_col.update_one({"id": "bot_settings"}, {"$addToSet": {"admins": new_admin}})
    set_bot_commands()
    bot.reply_to(message, f"✅ `{new_admin}` is now an Admin!", parse_mode="Markdown")

@bot.message_handler(commands=["rmadmin"])
def cmd_rmadmin(message):
    if message.chat.id != MAIN_ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Usage: `/rmadmin UserID`", parse_mode="Markdown")
    rm_admin = int(parts[1])
    if rm_admin == MAIN_ADMIN_ID: return bot.reply_to(message, "❌ Cannot remove Main Admin.")
    settings_col.update_one({"id": "bot_settings"}, {"$pull": {"admins": rm_admin}})
    set_bot_commands()
    bot.reply_to(message, f"✅ `{rm_admin}` removed from Admins.", parse_mode="Markdown")

@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not is_admin(message.chat.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Usage: `/ban UserID`", parse_mode="Markdown")
    uid = int(parts[1])
    users_col.update_one({"user_id": uid}, {"$set": {"banned": True}}, upsert=True)
    clear_cache(uid)
    bot.reply_to(message, f"🚫 User `{uid}` banned.", parse_mode="Markdown")

@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not is_admin(message.chat.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Usage: `/unban UserID`", parse_mode="Markdown")
    uid = int(parts[1])
    users_col.update_one({"user_id": uid}, {"$set": {"banned": False}})
    clear_cache(uid)
    bot.reply_to(message, f"✅ User `{uid}` unbanned.", parse_mode="Markdown")

@bot.message_handler(commands=["rename"])
def cmd_rename(message):
    if not is_admin(message.chat.id): return
    content = message.text.replace("/rename", "", 1).strip().split("|")
    if len(content) != 2: return bot.reply_to(message, "⚠️ Usage: `/rename Old_Name | New_Name`", parse_mode="Markdown")
    old_name, new_name = content[0].strip(), content[1].strip()
    docs = list(files_col.find({"base_title": clean_name(old_name)}))
    if not docs: return bot.reply_to(message, f"😔 '{old_name}' not found.", parse_mode="Markdown")
    count = 0
    for doc in docs:
        s_num, e_num = doc.get("s_num", 1), doc.get("e_num")
        display = f"{new_name} S{s_num:02d} E{e_num:02d}" if e_num else new_name
        files_col.update_one({"_id": doc["_id"]}, {"$set": {"base_title": clean_name(new_name), "list_title": new_name, "file_name": display}})
        count += 1
    bot.reply_to(message, f"✅ `{count}` files renamed to `{new_name}`", parse_mode="Markdown")

@bot.message_handler(commands=["delete"])
def cmd_delete_menu(message):
    if not is_admin(message.chat.id): return
    results = list(files_col.aggregate([{"$group": {"_id": "$base_title", "list_title": {"$first": "$list_title"}}}, {"$sort": {"list_title": 1}}, {"$limit": 30}]))
    if not results: return bot.reply_to(message, "🚫 Database is empty.")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in results:
        title = r.get("list_title") or r["_id"].title()
        markup.add(types.InlineKeyboardButton(f"🗑️ {title}", callback_data=f"askdel|{r['_id'][:40]}"))
    bot.send_message(message.chat.id, "❌ *Delete Panel*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["post"])
def cmd_post(message):
    if not is_admin(message.chat.id): return
    content = message.text.replace("/post", "", 1).strip().split("|")
    if not content[0].strip(): return bot.reply_to(message, "⚠️ Usage: `/post Movie Name | Details`", parse_mode="Markdown")
    name  = content[0].strip()
    extra = content[1].strip() if len(content) > 1 else "Watch Now!"
    text  = f"🎬 *New Release Added!*\n\n📌 *{name}*\nℹ️ {extra}\n\n👉 [{name}]({get_deep_link(name)})"
    try:
        _, poster, _, _ = get_tmdb_info(name)
        if poster: bot.send_photo(CHANNEL_USERNAME, poster, caption=text, parse_mode="Markdown")
        else: bot.send_message(CHANNEL_USERNAME, text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, "✅ Posted to channel successfully!")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not is_admin(message.chat.id) or not message.reply_to_message: return
    users = list(users_col.find({"banned": {"$ne": True}}, {"user_id": 1}))
    bot.reply_to(message, f"🚀 Broadcasting to {len(users)} users...")
    sent = failed = 0
    for u in users:
        try:
            bot.copy_message(u["user_id"], message.chat.id, message.reply_to_message.message_id)
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    bot.send_message(MAIN_ADMIN_ID, f"✅ Broadcast Complete!\n✔️ Success: `{sent}`\n❌ Failed: `{failed}`", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# 9. FILE INDEXING
# ═══════════════════════════════════════════════════════

@bot.message_handler(content_types=["video", "document"])
def index_files(message):
    if not is_admin(message.chat.id): return
    try:
        raw     = message.caption or (message.document.file_name if message.document else "Unknown")
        file_id = message.video.file_id if message.video else message.document.file_id
        size    = (message.video.file_size if message.video else message.document.file_size) or 0

        quality = extract_quality(raw)

        s_m   = re.search(r"(?i)(?:season|s)\s*(\d+)", raw)
        e_m   = re.search(r"(?i)(?:episode|ep|e)\s*(\d+)", raw)
        s_num = int(s_m.group(1)) if s_m else 1
        e_num = int(e_m.group(1)) if e_m else None

        split_point = re.split(r"(?i)season|episode|ep|s\d+[^a-zA-Z]|e\d+[^a-zA-Z]", raw)[0]
        list_title  = re.sub(r"\[.*?\]|\(.*?\)", "", split_point).strip()
        base_title  = clean_name(split_point)

        if not base_title:
            return bot.reply_to(message, "⚠️ Title not detected. Please add a name in the caption.")

        display = f"{list_title} S{s_num:02d} E{e_num:02d}" if e_num else list_title

        files_col.update_one(
            {"file_id": file_id},
            {"$set": {"file_name": display, "base_title": base_title, "list_title": list_title,
                      "s_num": s_num, "e_num": e_num, "quality": quality, "file_size": size, "file_id": file_id}},
            upsert=True
        )
        bot.reply_to(message, f"✅ Indexed: *{display}* `[{quality.upper()}]`", parse_mode="Markdown")
    except Exception as e:
        log.error(f"Index Error: {e}")
        bot.reply_to(message, f"⚠️ Error: {e}")

# ═══════════════════════════════════════════════════════
# 10. SMART SEARCH
# ═══════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: True)
def cmd_search(message):
    if message.text and message.text.startswith("/"): return

    register_user(message)
    uid = message.chat.id

    if is_banned(uid): return bot.reply_to(message, "❌ You are banned.")
    if not is_subscribed(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"),
            types.InlineKeyboardButton("🔄 Check Again", callback_data="check_sub")
        )
        return bot.reply_to(message, f"❌ Please join our channel first!\n👉 {CHANNEL_USERNAME}", reply_markup=markup)
    if is_rate_limited(uid): return bot.reply_to(message, "⚡ Please slow down! Max 5 requests per 10 seconds.")

    query        = message.text.strip()
    search_query = clean_name(query)
    if not search_query: return

    try: searches_col.update_one({"query": query.lower()}, {"$inc": {"count": 1}}, upsert=True)
    except Exception: pass

    db_results = list(files_col.find({"$text": {"$search": search_query}}).sort([("score", {"$meta": "textScore"})]))
    if not db_results:
        words      = search_query.split()
        db_results = list(files_col.find({"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words]}))

    tmdb_title, poster, is_movie, rating = get_tmdb_info(query)
    display_title = tmdb_title or (db_results[0].get("list_title", query.title()) if db_results else query.title())
    rating_text   = f"⭐ {rating}/10" if rating else "⭐ N/A"
    caption       = f"🎬 *{display_title}*\n{rating_text}\n\n"
    markup        = types.InlineKeyboardMarkup(row_width=2)

    if not db_results:
        caption += "😔 We don't have this movie yet."
        markup.add(types.InlineKeyboardButton("🙋 Request Admin", callback_data=f"quickreq|{query[:40]}"))
    else:
        if is_movie or not any(f.get("e_num") for f in db_results):
            markup.add(types.InlineKeyboardButton("🎬 Watch Now", callback_data=f"movie_q|{search_query[:30]}"))
        else:
            seasons = sorted(set(f["s_num"] for f in db_results))
            markup.add(*[types.InlineKeyboardButton(f"📂 Season {s}", callback_data=f"season|{search_query[:30]}|{s}") for s in seasons])

    try:
        if poster: bot.send_photo(uid, poster, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:      bot.send_message(uid, caption, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Search reply: {e}")

# ═══════════════════════════════════════════════════════
# 11. BULLETPROOF CALLBACK HANDLER
# ═══════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data  = call.data.split("|")
    uid   = call.message.chat.id
    cmd   = data[0]
    timer = get_settings().get("auto_delete_min", 0)

    try:
        if cmd == "check_sub":
            clear_cache(uid)
            if is_subscribed(uid):
                bot.answer_callback_query(call.id, "✅ Join confirmed! You can search now.", show_alert=True)
                try: bot.delete_message(uid, call.message.message_id)
                except Exception: pass
            else:
                bot.answer_callback_query(call.id, "❌ You haven't joined yet!", show_alert=True)
            return

        elif cmd == "page":
            send_list_page(uid, int(data[1]), call.message.message_id)

        elif cmd == "movie_q":
            q     = data[1]
            files = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "e_num": None}))
            if not files: files = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}}))
            markup          = types.InlineKeyboardMarkup(row_width=3)
            qualities_added = set()
            q_btns          = []
            for f in files:
                qual = f.get("quality", "hd").lower()
                if qual not in qualities_added:
                    q_btns.append(types.InlineKeyboardButton(f"🎬 {qual.upper()}", callback_data=f"file|{f['_id']}"))
                    qualities_added.add(qual)
            if q_btns: markup.add(*q_btns)
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"back|{q}"))
            try:
                bot.edit_message_caption("👇 *Select Quality:*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                bot.send_message(uid, "👇 Select Quality:", reply_markup=markup)

        elif cmd == "season":
            q, s_num  = data[1], int(data[2])
            eps       = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s_num}))
            qualities = sorted(set(f.get("quality", "hd").lower() for f in eps))
            markup    = types.InlineKeyboardMarkup(row_width=3)
            q_btns    = [types.InlineKeyboardButton(f"💿 {q2.upper()}", callback_data=f"sq|{q}|{s_num}|{q2}") for q2 in qualities]
            if q_btns: markup.add(*q_btns)
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"back|{q}"))
            try:
                bot.edit_message_caption(f"📂 *Season {s_num}*\n👇 *Select Quality:*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                bot.send_message(uid, f"Season {s_num} — Select Quality:", reply_markup=markup)

        elif cmd == "sq":
            q, s_num, qual = data[1], int(data[2]), data[3].lower()
            eps = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s_num, "quality": qual}).sort("e_num", 1))
            markup = types.InlineKeyboardMarkup(row_width=4)
            ep_btns = [types.InlineKeyboardButton(f"E{f['e_num']:02d}", callback_data=f"file|{f['_id']}") for f in eps if f.get("e_num")]
            if ep_btns: markup.add(*ep_btns)
            markup.row(
                types.InlineKeyboardButton("📥 All Episodes", callback_data=f"alleps|{q}|{s_num}|{qual}"),
                types.InlineKeyboardButton("🔙 Back",         callback_data=f"season|{q}|{s_num}")
            )
            try:
                bot.edit_message_caption(f"📂 *Season {s_num}* `[{qual.upper()}]`\n👇 *Select Episode:*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                bot.send_message(uid, f"Season {s_num} [{qual.upper()}] — Select Episode:", reply_markup=markup)

        elif cmd == "alleps":
            q     = data[1]
            s_num = int(data[2])
            qual  = data[3].lower() if len(data) > 3 else "hd"
            eps   = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s_num, "quality": qual}).sort("e_num", 1))
            bot.answer_callback_query(call.id, f"🚀 Sending {len(eps)} episodes...")
            for f in eps:
                cap = f"🎬 *{f['file_name']}*\n⚙️ `{f.get('quality','hd').upper()}`"
                if timer > 0: cap += f"\n⚠️ Deleting in {timer} mins."
                sent = bot.send_document(uid, f["file_id"], caption=cap, parse_mode="Markdown")
                schedule_delete(uid, sent.message_id, timer)
                time.sleep(0.5)

        elif cmd == "file":
            f = files_col.find_one({"_id": ObjectId(data[1])})
            if f:
                cap = f"🎬 *{f['file_name']}*\n⚙️ Quality: `{f.get('quality','hd').upper()}`\n🍿 {CHANNEL_USERNAME}"
                if timer > 0: cap += f"\n⚠️ Deleting in {timer} mins."
                sent = bot.send_document(uid, f["file_id"], caption=cap, parse_mode="Markdown")
                schedule_delete(uid, sent.message_id, timer)
            else:
                bot.answer_callback_query(call.id, "❌ File not found.", show_alert=True)
                return

        elif cmd == "back":
            q      = data[1]
            db_res = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}}))
            markup = types.InlineKeyboardMarkup(row_width=2)
            if not any(f.get("e_num") for f in db_res):
                markup.add(types.InlineKeyboardButton("🎬 Watch Now", callback_data=f"movie_q|{q}"))
            else:
                seasons = sorted(set(f["s_num"] for f in db_res))
                markup.add(*[types.InlineKeyboardButton(f"📂 Season {s}", callback_data=f"season|{q}|{s}") for s in seasons])
            try:
                bot.edit_message_caption("👇 *Select Option:*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                bot.send_message(uid, "👇 Select Option:", reply_markup=markup)

        elif cmd == "askdel":
            if not is_admin(uid): return
            key   = data[1]
            count = files_col.count_documents({"base_title": {"$regex": key, "$options": "i"}})
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Yes, Delete", callback_data=f"finaldel|{key}"),
                types.InlineKeyboardButton("❌ Cancel",      callback_data="cancel_del")
            )
            bot.edit_message_text(f"⚠️ Are you sure you want to delete `{count}` files matching '{key.title()}'?", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        elif cmd == "finaldel":
            if not is_admin(uid): return
            result = files_col.delete_many({"base_title": {"$regex": data[1], "$options": "i"}})
            bot.edit_message_text(f"✅ `{result.deleted_count}` files deleted successfully.", uid, call.message.message_id, parse_mode="Markdown")

        elif cmd == "cancel_del":
            bot.edit_message_text("❌ Deletion cancelled.", uid, call.message.message_id)

        elif cmd == "quickreq":
            title = data[1]
            if not requests_col.find_one({"title_lower": title.lower(), "status": "pending"}):
                db_res = requests_col.insert_one({"user_id": uid, "title": title, "title_lower": title.lower(), "status": "pending"})
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("✅ Approve", callback_data=f"reqok|{db_res.inserted_id}"),
                    types.InlineKeyboardButton("❌ Reject",  callback_data=f"reqno|{db_res.inserted_id}")
                )
                for admin_id in get_settings().get("admins", [MAIN_ADMIN_ID]):
                    try: bot.send_message(admin_id, f"🔔 *Quick Request!*\n`{title}`\nUser: `{uid}`", reply_markup=markup, parse_mode="Markdown")
                    except Exception: pass
            bot.answer_callback_query(call.id, f"✅ '{title}' requested successfully!", show_alert=True)

        elif cmd in ("reqok", "reqno"):
            req = requests_col.find_one({"_id": ObjectId(data[1])})
            if not req:
                bot.answer_callback_query(call.id, "Request not found.", show_alert=True)
                return
            action = "approved" if cmd == "reqok" else "rejected"
            requests_col.update_one({"_id": ObjectId(data[1])}, {"$set": {"status": action}})
            title   = req["title"]
            user_id = req["user_id"]

            if action == "approved":
                deep_link = get_deep_link(title)
                caption   = f"✅ Your requested movie *{title}* is now available!\n\n👉 [{title}]({deep_link})"
                _, poster, _, _ = get_tmdb_info(title)
                try:
                    if poster: bot.send_photo(user_id, poster, caption=caption, parse_mode="Markdown")
                    else:      bot.send_message(user_id, caption, parse_mode="Markdown", disable_web_page_preview=True)
                except Exception: pass
            else:
                try: bot.send_message(user_id, f"😔 Sorry! *{title}* is currently unavailable.", parse_mode="Markdown")
                except Exception: pass

            emoji = "✅" if action == "approved" else "❌"
            bot.edit_message_text(f"{emoji} `{action}`: *{title}*", uid, call.message.message_id, parse_mode="Markdown")

    except Exception as e:
        log.error(f"Callback [{call.data}]: {e}")
        bot.answer_callback_query(call.id, "⚠️ Something went wrong.", show_alert=True)
        return

    try: bot.answer_callback_query(call.id)
    except Exception: pass

# ═══════════════════════════════════════════════════════
# 12. FLASK & STARTUP
# ═══════════════════════════════════════════════════════

@flask_app.route("/")
def health():
    return "🚀 RiyajMovieBot V6.0 ACTIVE!"

def run_bot():
    setup_indexes()
    set_bot_commands()
    try: bot.remove_webhook()
    except Exception: pass
    log.info("🤖 Polling started...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
