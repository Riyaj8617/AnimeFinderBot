import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server V3.5 (The Pro-Admin Edition) is Running...")

# --- Credentials ---
BOT_TOKEN = '8351560947:AAEuuIpuOqU9rLJpwJfVrudwsrGNW-iXUWA'
TMDB_API_KEY = 'eac1f699fd04bfed4063efc4e9166925'
MONGO_URI = 'mongodb+srv://riya8617:Riyaj%40786@cluster0.lhmz2q8.mongodb.net/?appName=Cluster0'
ADMIN_ID = 7141977665 
CHANNEL_USERNAME = '@RAnimeTV'
BOT_USERNAME = 'RiyajFinderBot'

client = MongoClient(MONGO_URI)
db = client['RiyajMovieBot']
files_col = db['files']
users_col = db['users']       
searches_col = db['searches'] 
settings_col = db['settings'] # To store admin settings

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Initial Settings ---
if not settings_col.find_one({"id": "bot_settings"}):
    settings_col.insert_one({"id": "bot_settings", "auto_delete_min": 0})

def set_bot_commands():
    try:
        user_cmds = [
            telebot.types.BotCommand("start", "Start the bot 🚀"),
            telebot.types.BotCommand("list", "View all collections 📚"),
            telebot.types.BotCommand("menu", "Open main menu 📱")
        ]
        bot.set_my_commands(user_cmds)
        admin_cmds = [
            telebot.types.BotCommand("start", "Start the bot 🚀"),
            telebot.types.BotCommand("stats", "Admin Dashboard 📊"),
            telebot.types.BotCommand("topsearch", "View Viral Searches 🔥"),
            telebot.types.BotCommand("settime", "Set Auto-Delete (Minutes) ⏰"),
            telebot.types.BotCommand("delete", "Manage Database 🗑️"),
            telebot.types.BotCommand("post", "Post to Channel 🖼"),
            telebot.types.BotCommand("broadcast", "Broadcast Message 📢")
        ]
        bot.set_my_commands(admin_cmds, scope=telebot.types.BotCommandScopeChat(ADMIN_ID))
    except: pass

# --- Helper Functions ---
def get_deep_link(movie_name):
    payload = re.sub(r'[^a-zA-Z0-9]', '_', movie_name)[:60]
    return f"https://t.me/{BOT_USERNAME}?start={payload}"

def is_subscribed(user_id):
    if user_id == ADMIN_ID: return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except: return False

def is_banned(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get('banned', False) if user else False

def clean_name(text):
    text = re.sub(r'\[.*?\]', ' ', text) 
    text = re.sub(r'@[a-zA-Z0-9_]+', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\(\d{4}\)', ' ', text)
    junk_words = r'(?i)(title|1080p|720p|480p|hevc|10bit|amzn|web-?dl|bluray|brrip|hindi audio|hindi dub|dual audio|esub|mkv|mp4|full movie|official)'
    text = re.sub(junk_words, ' ', text)
    clean = re.sub(r'[^a-zA-Z0-9]', ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()

def delete_timer(chat_id, message_id, minutes):
    time.sleep(minutes * 60)
    try: bot.delete_message(chat_id, message_id)
    except: pass

# ==========================================
# 1. ADMIN COMMANDS (BAN, STATS, SETTINGS)
# ==========================================

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id != ADMIN_ID: return
    try:
        uid = int(message.text.split()[1])
        users_col.update_one({"user_id": uid}, {"$set": {"banned": True}}, upsert=True)
        bot.reply_to(message, f"🚫 User {uid} has been banned.")
    except: bot.reply_to(message, "Usage: `/ban UserID`")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id != ADMIN_ID: return
    try:
        uid = int(message.text.split()[1])
        users_col.update_one({"user_id": uid}, {"$set": {"banned": False}}, upsert=True)
        bot.reply_to(message, f"✅ User {uid} has been unbanned.")
    except: bot.reply_to(message, "Usage: `/unban UserID`")

@bot.message_handler(commands=['settime'])
def set_delete_time(message):
    if message.chat.id != ADMIN_ID: return
    try:
        mins = int(message.text.split()[1])
        settings_col.update_one({"id": "bot_settings"}, {"$set": {"auto_delete_min": mins}})
        status = f"✅ Auto-Delete set to {mins} minutes." if mins > 0 else "❌ Auto-Delete Disabled."
        bot.reply_to(message, status)
    except: bot.reply_to(message, "Usage: `/settime <minutes>` (0 to disable)")

@bot.message_handler(commands=['topsearch'])
def view_top_searches(message):
    if message.chat.id != ADMIN_ID: return
    top = searches_col.find().sort("count", -1).limit(10)
    res = "🔥 **Trending Searches:**\n\n"
    for i, s in enumerate(top, 1):
        res += f"{i}. {s['query'].title()} ({s['count']} times)\n"
    bot.reply_to(message, res, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id != ADMIN_ID: return
    sets = settings_col.find_one({"id": "bot_settings"})
    timer = f"{sets['auto_delete_min']} Min" if sets['auto_delete_min'] > 0 else "OFF"
    bot.reply_to(message, f"📊 **Pro Admin Dashboard:**\n\n👥 Users: {users_col.count_documents({})}\n🎬 Files: {files_col.count_documents({})}\n⏰ Auto-Delete: {timer}", parse_mode="Markdown")

# ==========================================
# 2. FILE UPLOAD & ADVANCED SCANNER
# ==========================================

@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    # 🧠 Advanced Regex for Season/Episode
    s_m = re.search(r'(?i)(?:season|s|season\s*[:\-])\s*(\d+)', raw_text)
    e_m = re.search(r'(?i)(?:episode|ep|e|episode\s*[:\-])\s*(\d+)', raw_text)
    
    s_num = int(s_m.group(1)) if s_m else 1
    e_num = int(e_m.group(1)) if e_m else None
    
    base_title = clean_name(re.split(r'(?i)season|episode|ep|s\d+|e\d+', raw_text)[0])
    display_name = f"{base_title.title()} S{s_num:02d} E{e_num:02d}" if e_num else base_title.title()

    files_col.update_one({"file_id": file_id}, {"$set": {"file_name": display_name, "base_title": base_title.lower(), "s_num": s_num, "e_num": e_num, "file_id": file_id}}, upsert=True)
    bot.reply_to(message, f"✅ Properly Indexed: {display_name}")

# ==========================================
# 3. SMART SEARCH & AUTO-DELETE LOGIC
# ==========================================

@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Join our channel first!**\n👉 {CHANNEL_USERNAME}")
        return
    
    query = message.text.lower()
    words = re.sub(r'[^a-zA-Z0-9\s]', ' ', query).split()
    if not words: return
    
    # Track viral searches
    searches_col.update_one({"query": " ".join(words)}, {"$inc": {"count": 1}}, upsert=True)
    
    db_results = list(files_col.find({"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words]}))
    tmdb_res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}").json()
    
    if tmdb_res.get('results'):
        item = tmdb_res['results'][0]
        title, is_movie = item.get('title') or item.get('name'), item.get('media_type') == 'movie'
        caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10\n\n"
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        
        if not db_results:
            caption += "⚠️ Hindi Dubbed not found. Request below."
            markup.add(telebot.types.InlineKeyboardButton("🙋‍♂️ Request", callback_data=f"req_{query[:15]}"))
        else:
            if is_movie:
                for f in db_results: markup.add(telebot.types.InlineKeyboardButton("🎬 Watch Now", callback_data=f"file_{f['_id']}"))
            else:
                seasons = sorted(list(set(f['s_num'] for f in db_results)))
                markup.add(*[telebot.types.InlineKeyboardButton(f"Season {s}", callback_data=f"list_{query[:15]}_{s}") for s in seasons])
        
        poster = f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get('poster_path') else None
        if poster: bot.send_photo(message.chat.id, poster, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else: bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# 4. CALLBACK & TIMER HANDLER
# ==========================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data.split('_')
    sets = settings_col.find_one({"id": "bot_settings"})
    timer_min = sets['auto_delete_min']
    
    if data[0] == "file":
        f = files_col.find_one({"_id": ObjectId(data[1])})
        if f:
            caption = f"🎬 **{f['file_name']}**\n🍿 Powered by @RAnimeTV"
            if timer_min > 0:
                caption += f"\n\n⚠️ **Note:** এই ভিডিওটি মাত্র {timer_min} মিনিট থাকবে, তারপর অটোমেটিক ডিলিট হয়ে যাবে।"
            
            sent_msg = bot.send_document(call.message.chat.id, f['file_id'], caption=caption)
            
            # Start Auto-Delete Timer
            if timer_min > 0:
                threading.Thread(target=delete_timer, args=(call.message.chat.id, sent_msg.message_id, timer_min)).start()

    # --- Other UI Logic ---
    elif data[0] == "list":
        q, s = data[1], int(data[2])
        episodes = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s}).sort("e_num", 1))
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        markup.add(*[telebot.types.InlineKeyboardButton(f"E{f['e_num']:02d}", callback_data=f"file_{f['_id']}") for f in episodes if f['e_num']])
        markup.row(telebot.types.InlineKeyboardButton("📥 All Episodes", callback_data=f"all_{q}_{s}"), telebot.types.InlineKeyboardButton("🔙 Back", callback_data=f"back_{q}"))
        bot.edit_message_caption(f"📂 **Season {s} Episodes:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data[0] == "all":
        eps = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}, "s_num": int(data[2])}).sort("e_num", 1))
        bot.answer_callback_query(call.id, f"🚀 Sending {len(eps)} episodes...")
        for f in eps:
            caption = f"🎬 **{f['file_name']}**"
            if timer_min > 0: caption += f"\n⚠️ Deleting in {timer_min} min."
            m = bot.send_document(call.message.chat.id, f['file_id'], caption=caption)
            if timer_min > 0: threading.Thread(target=delete_timer, args=(call.message.chat.id, m.message_id, timer_min)).start()
            time.sleep(1)

    elif data[0] == "back":
        db_res = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}}))
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        markup.add(*[telebot.types.InlineKeyboardButton(f"Season {s}", callback_data=f"list_{data[1]}_{s}") for s in sorted(list(set(f['s_num'] for f in db_res)))])
        bot.edit_message_caption("👇 **Select Season:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

@app.route('/')
def index(): return "🚀 V3.5 Pro-Admin Active!"

def run_bot():
    set_bot_commands()
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=60)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
