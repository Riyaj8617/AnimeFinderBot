import os
import re
import time
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

import requests
import telebot
from telebot import types
from flask import Flask
from pymongo import MongoClient, ASCENDING, TEXT
from bson.objectid import ObjectId
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 1. SETUP & CREDENTIALS
# ─────────────────────────────────────────────
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

print("🚀 Ultimate Flagship Server V5.0 (Perfect 10/10 Edition) is Running...")

BOT_TOKEN        = os.getenv("BOT_TOKEN")
TMDB_API_KEY     = os.getenv("TMDB_API_KEY")
MONGO_URI        = os.getenv("MONGO_URI")
MAIN_ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
BOT_USERNAME     = os.getenv("BOT_USERNAME")

# ─────────────────────────────────────────────
# 2. DATABASE & INDEXING (Grok's Fast Engine)
# ─────────────────────────────────────────────
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db     = client["RiyajMovieBot"]

files_col    = db["files"]
users_col    = db["users"]
searches_col = db["searches"]
settings_col = db["settings"]
requests_col = db["requests"]

def setup_indexes():
    try:
        files_col.create_index([("base_title", TEXT)])
        files_col.create_index([("file_id", ASCENDING)], unique=True)
        users_col.create_index([("user_id", ASCENDING)], unique=True)
        log.info("✅ MongoDB indexes ready")
    except Exception as e:
        log.warning(f"Index setup: {e}")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
flask_app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=20) # Thread Leak Fix

def get_settings():
    s = settings_col.find_one({"id": "bot_settings"})
    if not s:
        s = {"id": "bot_settings", "auto_delete_min": 0, "admins": [MAIN_ADMIN_ID]}
        settings_col.insert_one(s)
    return s

# ─────────────────────────────────────────────
# 3. ANTI-SPAM, CACHE & MULTI-ADMIN
# ─────────────────────────────────────────────
_rate_data = defaultdict(list)
_sub_cache = {}

def is_admin(user_id):
    s = get_settings()
    return user_id in s.get("admins", [MAIN_ADMIN_ID])

def is_rate_limited(user_id):
    if is_admin(user_id): return False
    now = time.time()
    _rate_data[user_id] = [t for t in _rate_data[user_id] if now - t < 10]
    if len(_rate_data[user_id]) >= 5: return True
    _rate_data[user_id].append(now)
    return False

def is_subscribed(user_id):
    if is_admin(user_id): return True 
    now = time.time()
    if user_id in _sub_cache and now - _sub_cache[user_id][1] < 300:
        return _sub_cache[user_id][0]
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        res = status in ("creator", "administrator", "member")
    except: res = False
    _sub_cache[user_id] = (res, now)
    return res

def is_banned(user_id):
    u = users_col.find_one({"user_id": user_id})
    return bool(u.get("banned", False)) if u else False

# ─────────────────────────────────────────────
# 4. HELPERS & FORMATTING
# ─────────────────────────────────────────────
def get_deep_link(movie_name):
    payload = re.sub(r"[^a-zA-Z0-9]", "_", movie_name)[:60]
    return f"https://t.me/{BOT_USERNAME}?start={payload}"

def clean_name_for_search(text):
    text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    text = re.sub(r"@[a-zA-Z0-9_]+|https?://\S+", " ", text)
    junk = r"(?i)\b(1080p|720p|480p|360p|hevc|10bit|amzn|web-?dl|bluray|brrip|hindi audio|hindi dub|dual audio|esub|mkv|mp4|full movie)\b"
    text = re.sub(junk, " ", text)
    return re.sub(r"[^a-zA-Z0-9]", " ", text).strip().lower()

def delete_after(chat_id, msg_id, minutes):
    time.sleep(minutes * 60)
    try: bot.delete_message(chat_id, msg_id)
    except: pass

def schedule_delete(chat_id, msg_id, minutes):
    if minutes > 0: executor.submit(delete_after, chat_id, msg_id, minutes)

def set_bot_commands():
    try:
        bot.delete_my_commands(scope=types.BotCommandScopeDefault())
        user_cmds = [
            types.BotCommand("start", "Start Bot 🚀"),
            types.BotCommand("list", "Collections 📚"),
            types.BotCommand("request", "Request Movie 🙋")
        ]
        bot.set_my_commands(user_cmds, scope=types.BotCommandScopeDefault())
        
        admin_cmds = user_cmds + [
            types.BotCommand("stats", "Dashboard 📊"),
            types.BotCommand("topsearch", "Viral Searches 🔥"),
            types.BotCommand("pendingreq", "Pending Requests 📋"),
            types.BotCommand("settime", "Auto-Delete ⏰"),
            types.BotCommand("rename", "Rename Movies ✏️"),
            types.BotCommand("delete", "Manage DB 🗑️"),
            types.BotCommand("post", "Channel Post 🖼"),
            types.BotCommand("broadcast", "Broadcast 📢"),
            types.BotCommand("ban", "Ban User 🚫"),
            types.BotCommand("unban", "Unban User ✅"),
            types.BotCommand("addadmin", "Add Admin 👑"),
            types.BotCommand("rmadmin", "Remove Admin ❌")
        ]
        s = get_settings()
        for admin_id in s.get("admins", [MAIN_ADMIN_ID]):
            try: bot.set_my_commands(admin_cmds, scope=types.BotCommandScopeChat(admin_id))
            except: pass
        log.info("✅ Menus updated")
    except Exception as e: log.error(f"Menu error: {e}")

# ─────────────────────────────────────────────
# 5. USER COMMANDS
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    users_col.update_one({"user_id": message.chat.id}, {"$set": {"user_id": message.chat.id}}, upsert=True)
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        message.text = parts[1].replace("_", " ")
        cmd_search(message)
        return
    bot.reply_to(message, "🎬 *Welcome to RiyajMovieBot!*\nSend me any movie or anime name.", parse_mode="Markdown")

@bot.message_handler(commands=["list"])
def cmd_list(message):
    if not is_subscribed(message.chat.id):
        return bot.reply_to(message, f"❌ **Join our channel!**\n👉 {CHANNEL_USERNAME}")
    send_list_page(message.chat.id, 0)

def send_list_page(chat_id, page, edit_msg_id=None):
    PAGE_SIZE = 15
    pipeline = [
        {"$group": {"_id": "$base_title", "list_title": {"$first": "$list_title"}}},
        {"$sort": {"list_title": 1}},
        {"$skip": page * PAGE_SIZE},
        {"$limit": PAGE_SIZE + 1}
    ]
    results = list(files_col.aggregate(pipeline))
    has_next = len(results) > PAGE_SIZE
    results = results[:PAGE_SIZE]

    if not results:
        bot.send_message(chat_id, "🚫 কোনো মুভি নেই।")
        return

    lines = [f"📚 *Our Collection* (Page {page+1}):\n"]
    for r in results:
        title = r.get("list_title", r["_id"].title())
        lines.append(f"🍿 [{title}]({get_deep_link(title)})")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"page|{page-1}"))
    if has_next: nav.append(types.InlineKeyboardButton("➡️ Next", callback_data=f"page|{page+1}"))
    if nav: markup.add(*nav)

    text = "\n".join(lines)
    if edit_msg_id:
        try: bot.edit_message_text(text, chat_id, edit_msg_id, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
        except: pass
    else: bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)

@bot.message_handler(commands=["request"])
def cmd_request(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(message, "📝 Use: `/request Movie Name`", parse_mode="Markdown")
    title = parts[1].strip()
    
    if requests_col.find_one({"title_lower": title.lower(), "status": "pending"}):
        return bot.reply_to(message, f"✅ `{title}` already requested!")
        
    res = requests_col.insert_one({"user_id": message.chat.id, "title": title, "title_lower": title.lower(), "status": "pending"})
    bot.reply_to(message, f"✅ Request sent to admin:\n🎬 *{title}*", parse_mode="Markdown")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"reqok|{res.inserted_id}"), types.InlineKeyboardButton("❌ Reject", callback_data=f"reqno|{res.inserted_id}"))
    
    s = get_settings()
    for admin_id in s.get("admins", [MAIN_ADMIN_ID]):
        try: bot.send_message(admin_id, f"🔔 *New Request!*\nTitle: `{title}`\nUser: `{message.chat.id}`", parse_mode="Markdown", reply_markup=markup)
        except: pass

# ─────────────────────────────────────────────
# 6. ADMIN COMMANDS (All Claude Handlers Added)
# ─────────────────────────────────────────────
@bot.message_handler(commands=["topsearch"])
def cmd_topsearch(message):
    if not is_admin(message.chat.id): return
    top = list(searches_col.find().sort("count", -1).limit(10))
    if not top: return bot.reply_to(message, "🚫 কোনো search data নেই এখনো।")
    lines = ["🔥 *Trending Searches:*\n"]
    for i, s in enumerate(top, 1):
        lines.append(f"{i}. {s['query'].title()} — `{s['count']}` বার")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["addadmin"])
def cmd_addadmin(message):
    if message.chat.id != MAIN_ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Use: `/addadmin UserID`", parse_mode="Markdown")
    new_admin = int(parts[1])
    settings_col.update_one({"id": "bot_settings"}, {"$addToSet": {"admins": new_admin}})
    set_bot_commands()
    bot.reply_to(message, f"✅ `{new_admin}` is now an Admin!", parse_mode="Markdown")

@bot.message_handler(commands=["rmadmin"])
def cmd_rmadmin(message):
    if message.chat.id != MAIN_ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Use: `/rmadmin UserID`", parse_mode="Markdown")
    rm_admin = int(parts[1])
    if rm_admin == MAIN_ADMIN_ID: return bot.reply_to(message, "❌ Cannot remove Main Admin.")
    settings_col.update_one({"id": "bot_settings"}, {"$pull": {"admins": rm_admin}})
    set_bot_commands()
    bot.reply_to(message, f"✅ `{rm_admin}` removed from Admins.", parse_mode="Markdown")

@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not is_admin(message.chat.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Use: `/ban UserID`", parse_mode="Markdown")
    uid = int(parts[1])
    users_col.update_one({"user_id": uid}, {"$set": {"banned": True}}, upsert=True)
    if uid in _sub_cache: del _sub_cache[uid]
    bot.reply_to(message, f"🚫 User `{uid}` banned.", parse_mode="Markdown")

@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not is_admin(message.chat.id): return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit(): return bot.reply_to(message, "⚠️ Use: `/unban UserID`", parse_mode="Markdown")
    uid = int(parts[1])
    users_col.update_one({"user_id": uid}, {"$set": {"banned": False}})
    if uid in _sub_cache: del _sub_cache[uid]
    bot.reply_to(message, f"✅ User `{uid}` unbanned.", parse_mode="Markdown")

@bot.message_handler(commands=["post"])
def cmd_post(message):
    if not is_admin(message.chat.id): return
    content = message.text.replace("/post", "", 1).strip().split("|")
    if len(content) < 1 or not content[0].strip(): return bot.reply_to(message, "⚠️ Use: `/post Movie Name | Info`", parse_mode="Markdown")
    name = content[0].strip()
    extra = content[1].strip() if len(content) > 1 else "Watch Now!"
    deep_link = get_deep_link(name)
    
    text = f"🎬 **New Release Added!**\n\n📌 **Title:** {name}\nℹ️ {extra}\n\n👇 **Click Below to Watch:**\n👉 [{name}]({deep_link})"
    try:
        res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}", timeout=8).json()
        poster = f"https://image.tmdb.org/t/p/w500{res['results'][0]['poster_path']}" if res.get("results") and res["results"][0].get("poster_path") else None
        if poster: bot.send_photo(CHANNEL_USERNAME, poster, caption=text, parse_mode="Markdown")
        else: bot.send_message(CHANNEL_USERNAME, text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, "✅ Posted to channel!")
    except Exception as e: bot.reply_to(message, f"⚠️ Error: {e}")

@bot.message_handler(commands=["rename"])
def cmd_rename(message):
    if not is_admin(message.chat.id): return
    content = message.text.replace("/rename", "", 1).strip().split("|")
    if len(content) != 2: return bot.reply_to(message, "⚠️ Use: `/rename Old Name | New Name`", parse_mode="Markdown")
    
    old_name, new_name = content[0].strip(), content[1].strip()
    clean_old = clean_name_for_search(old_name)
    clean_new = clean_name_for_search(new_name)

    docs = list(files_col.find({"base_title": clean_old}))
    if not docs: return bot.reply_to(message, f"😔 No files matching: `{old_name}`")

    count = 0
    for doc in docs:
        s_num, e_num = doc.get("s_num", 1), doc.get("e_num")
        display = f"{new_name} S{s_num:02d} E{e_num:02d}" if e_num else new_name
        files_col.update_one({"_id": doc["_id"]}, {"$set": {"base_title": clean_new, "list_title": new_name, "file_name": display}})
        count += 1
    bot.reply_to(message, f"✅ `{count}` files renamed to `{new_name}`", parse_mode="Markdown")

@bot.message_handler(commands=["pendingreq"])
def cmd_pending_requests(message):
    if not is_admin(message.chat.id): return
    pending = list(requests_col.find({"status": "pending"}).limit(10))
    if not pending: return bot.reply_to(message, "✅ No pending requests.")
    text, markup = "📋 *Pending:*\n\n", types.InlineKeyboardMarkup(row_width=2)
    for r in pending:
        text += f"🎬 `{r['title']}`\n"
        markup.add(types.InlineKeyboardButton(f"✅ {r['title'][:15]}", callback_data=f"reqok|{r['_id']}"), types.InlineKeyboardButton(f"❌ {r['title'][:15]}", callback_data=f"reqno|{r['_id']}"))
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message.chat.id): return
    s = get_settings()
    timer = f"{s.get('auto_delete_min', 0)} Min"
    admins = len(s.get("admins", [MAIN_ADMIN_ID]))
    bot.reply_to(message, f"📊 *Dashboard*\n👥 Users: {users_col.count_documents({})}\n🎬 Files: {files_col.count_documents({})}\n⏰ Auto-Delete: {timer}\n👑 Admins: {admins}", parse_mode="Markdown")

@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message.chat.id): return
    try:
        mins = int(message.text.split()[1])
        settings_col.update_one({"id": "bot_settings"}, {"$set": {"auto_delete_min": mins}})
        bot.reply_to(message, f"✅ Auto-Delete set to `{mins}` mins.", parse_mode="Markdown")
    except: bot.reply_to(message, "Use: `/settime <minutes>`")

@bot.message_handler(commands=["delete"])
def cmd_delete_menu(message):
    if not is_admin(message.chat.id): return
    results = list(files_col.aggregate([{"$group": {"_id": "$base_title", "list_title": {"$first": "$list_title"}}}, {"$limit": 30}]))
    if not results: return bot.reply_to(message, "🚫 Database empty.")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in results:
        title = r.get("list_title", r["_id"].title())
        markup.add(types.InlineKeyboardButton(f"🗑️ {title}", callback_data=f"askdel|{r['_id'][:40]}"))
    bot.send_message(message.chat.id, "❌ *Delete Panel*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not is_admin(message.chat.id) or not message.reply_to_message: return
    # 🔥 BANNED USER SKIP FIX APPLIED
    users = list(users_col.find({"banned": {"$ne": True}}, {"user_id": 1}))
    bot.reply_to(message, f"🚀 Broadcasting to {len(users)} users...")
    sent = 0
    for u in users:
        try:
            bot.copy_message(u["user_id"], message.chat.id, message.reply_to_message.message_id)
            sent += 1
            time.sleep(0.05)
        except: pass
    bot.send_message(MAIN_ADMIN_ID, f"✅ Broadcast done! Sent: `{sent}`")

# ─────────────────────────────────────────────
# 7. INDEXING & SEARCH
# ─────────────────────────────────────────────
@bot.message_handler(content_types=["video", "document"])
def index_files(message):
    if not is_admin(message.chat.id): return
    try:
        raw = message.caption or (message.document.file_name if message.document else "Unknown")
        file_id = message.video.file_id if message.video else message.document.file_id

        s_m = re.search(r"(?i)(?:season|s)\s*(\d+)", raw)
        e_m = re.search(r"(?i)(?:episode|ep|e)\s*(\d+)", raw)
        s_num = int(s_m.group(1)) if s_m else 1
        e_num = int(e_m.group(1)) if e_m else None

        split_point = re.split(r"(?i)season|episode|ep|s\d+[^a-zA-Z]|e\d+[^a-zA-Z]", raw)[0]
        list_title = re.sub(r'\[.*?\]|\(.*?\)', '', split_point).strip()
        base_title = clean_name_for_search(split_point)
        
        display = f"{list_title} S{s_num:02d} E{e_num:02d}" if e_num else list_title

        files_col.update_one(
            {"file_id": file_id},
            {"$set": {"file_name": display, "base_title": base_title, "list_title": list_title, "s_num": s_num, "e_num": e_num, "file_id": file_id}},
            upsert=True
        )
        bot.reply_to(message, f"✅ Indexed: *{display}*", parse_mode="Markdown")
    except Exception as e: log.error(f"Index error: {e}")

@bot.message_handler(func=lambda m: True)
def cmd_search(message):
    if message.text.startswith("/"): return
    uid = message.chat.id
    if is_banned(uid): return bot.reply_to(message, "❌ Banned.")
    if not is_subscribed(uid): return bot.reply_to(message, f"❌ Join channel!\n👉 {CHANNEL_USERNAME}")
    if is_rate_limited(uid): return bot.reply_to(message, "⚡ Please wait! Max 5 requests per 10s.")

    query = message.text.strip()
    search_query = clean_name_for_search(query)
    if not search_query: return

    try: searches_col.update_one({"query": query.lower()}, {"$inc": {"count": 1}}, upsert=True)
    except: pass

    db_results = list(files_col.find({"$text": {"$search": search_query}}).sort([("score", {"$meta": "textScore"})]))
    if not db_results:
        words = search_query.split()
        db_results = list(files_col.find({"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words]}))

    tmdb_title, poster, is_movie = None, None, True
    try:
        res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}", timeout=8).json()
        if res.get("results"):
            item = res["results"][0]
            tmdb_title = item.get("title") or item.get("name")
            is_movie = item.get("media_type") == "movie"
            if item.get("poster_path"): poster = f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
    except: pass

    display_title = tmdb_title or (db_results[0].get("list_title", query.title()) if db_results else query.title())
    caption = f"🎬 *{display_title}*\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)

    if not db_results:
        caption += "😔 Not in our database yet."
        markup.add(types.InlineKeyboardButton("🙋 Request Admin", callback_data=f"quickreq|{query[:40]}"))
    else:
        if is_movie or not any(f.get("e_num") for f in db_results):
            for f in db_results[:5]: markup.add(types.InlineKeyboardButton("🎬 Watch Now", callback_data=f"file|{f['_id']}"))
        else:
            seasons = sorted(set(f["s_num"] for f in db_results))
            markup.add(*[types.InlineKeyboardButton(f"Season {s}", callback_data=f"season|{search_query[:30]}|{s}") for s in seasons])

    if poster: bot.send_photo(uid, poster, caption=caption, reply_markup=markup, parse_mode="Markdown")
    else: bot.send_message(uid, caption, reply_markup=markup, parse_mode="Markdown")

# ─────────────────────────────────────────────
# 8. BULLETPROOF CALLBACK HANDLER
# ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data.split("|")
    uid = call.message.chat.id
    cmd = data[0]
    timer = get_settings().get("auto_delete_min", 0)

    try:
        if cmd == "page":
            send_list_page(uid, int(data[1]), call.message.message_id)
            
        elif cmd == "file":
            f = files_col.find_one({"_id": ObjectId(data[1])})
            if f:
                cap = f"🎬 *{f['file_name']}*\n🍿 Powered by {CHANNEL_USERNAME}"
                if timer > 0: cap += f"\n⚠️ Deleting in {timer} minutes."
                sent = bot.send_document(uid, f["file_id"], caption=cap, parse_mode="Markdown")
                schedule_delete(uid, sent.message_id, timer)

        elif cmd == "season":
            q, s_num = data[1], int(data[2])
            eps = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s_num}).sort("e_num", 1))
            markup = types.InlineKeyboardMarkup(row_width=4)
            markup.add(*[types.InlineKeyboardButton(f"E{f['e_num']:02d}", callback_data=f"file|{f['_id']}") for f in eps if f.get("e_num")])
            markup.row(types.InlineKeyboardButton("📥 All Episodes", callback_data=f"alleps|{q}|{s_num}"), types.InlineKeyboardButton("🔙 Back", callback_data=f"back|{q}"))
            bot.edit_message_caption(f"📂 *Season {s_num}*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        elif cmd == "alleps":
            eps = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}, "s_num": int(data[2])}).sort("e_num", 1))
            bot.answer_callback_query(call.id, f"🚀 Sending {len(eps)} eps...")
            for f in eps:
                cap = f"🎬 *{f['file_name']}*"
                if timer > 0: cap += f"\n⚠️ Deleting in {timer} min."
                sent = bot.send_document(uid, f["file_id"], caption=cap, parse_mode="Markdown")
                schedule_delete(uid, sent.message_id, timer)
                time.sleep(0.5)

        elif cmd == "back":
            db_res = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}}))
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(*[types.InlineKeyboardButton(f"Season {s}", callback_data=f"season|{data[1]}|{s}") for s in sorted(set(f["s_num"] for f in db_res))])
            bot.edit_message_caption("👇 *Select Season:*", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        elif cmd == "askdel":
            key = data[1]
            count = files_col.count_documents({"base_title": key})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Yes", callback_data=f"finaldel|{key}"), types.InlineKeyboardButton("❌ No", callback_data="cancel_del"))
            bot.edit_message_text(f"⚠️ Delete `{key}`?\nRemoves {count} files.", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

        elif cmd == "finaldel":
            res = files_col.delete_many({"base_title": data[1]})
            bot.edit_message_text(f"✅ {res.deleted_count} files deleted.", uid, call.message.message_id)

        elif cmd == "cancel_del": bot.edit_message_text("❌ Cancelled.", uid, call.message.message_id)
        
        elif cmd == "quickreq":
            if not requests_col.find_one({"title_lower": data[1].lower(), "status": "pending"}):
                # 🔥 Claude-এর সাজেশন অনুযায়ী নাম বদলানো হলো (db_res)
                db_res = requests_col.insert_one({"user_id": uid, "title": data[1], "title_lower": data[1].lower(), "status": "pending"})
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"reqok|{db_res.inserted_id}"), 
                           types.InlineKeyboardButton("❌ Reject", callback_data=f"reqno|{db_res.inserted_id}"))
                
                for admin_id in get_settings().get("admins", [MAIN_ADMIN_ID]):
                    try: bot.send_message(admin_id, f"🔔 *Quick Request!*\n`{data[1]}`\nUser: `{uid}`", reply_markup=markup, parse_mode="Markdown")
                    except: pass
            bot.answer_callback_query(call.id, "✅ Requested!", show_alert=True)
            
        elif cmd in ("reqok", "reqno"):
            req = requests_col.find_one({"_id": ObjectId(data[1])})
            if req:
                action = "approved" if cmd == "reqok" else "rejected"
                requests_col.update_one({"_id": ObjectId(data[1])}, {"$set": {"status": action}})
                
                title = req["title"]
                user_id = req["user_id"]
                
                if action == "approved":
                    deep_link = get_deep_link(title)
                    caption = f"✅ আপনার রিকোয়েস্ট করা মুভিটি আপলোড করা হয়েছে!\n\n👇 **দেখার জন্য নিচে ক্লিক করুন:**\n👉 **[{title}]({deep_link})**"
                    
                    poster = None
                    try:
                        # 🔥 Claude-এর সাজেশন অনুযায়ী নাম বদলানো হলো (tmdb_res)
                        tmdb_res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={title}", timeout=8).json()
                        if tmdb_res.get("results") and tmdb_res["results"][0].get("poster_path"):
                            poster = f"https://image.tmdb.org/t/p/w500{tmdb_res['results'][0]['poster_path']}"
                    except: pass
                    
                    try:
                        if poster: bot.send_photo(user_id, poster, caption=caption, parse_mode="Markdown")
                        else: bot.send_message(user_id, caption, parse_mode="Markdown", disable_web_page_preview=True)
                    except: pass
                else:
                    msg = f"😔 দুঃখিত! **{title}** মুভিটি এই মুহূর্তে পাওয়া যাচ্ছে না।"
                    try: bot.send_message(user_id, msg, parse_mode="Markdown")
                    except: pass
                
                emoji = "✅" if action == "approved" else "❌"
                bot.edit_message_text(f"{emoji} Request `{action}`: *{title}*", uid, call.message.message_id, parse_mode="Markdown")
                
    except Exception as e: log.error(f"Callback error: {e}")
    try: bot.answer_callback_query(call.id)
    except: pass

@flask_app.route("/")
def health(): return "🚀 RiyajMovieBot V5.0 (Perfect 10) ACTIVE!"

def run_bot():
    setup_indexes()
    set_bot_commands()
    try: bot.remove_webhook()
    except: pass
    log.info("🤖 Polling started...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
