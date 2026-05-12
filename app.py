import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server V3.0 (Dynamic UI & Smart Search) is Running...")

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

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- 🛠 Smart Menu Setup ---
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
            telebot.types.BotCommand("list", "View all collections 📚"),
            telebot.types.BotCommand("stats", "View admin dashboard 📊"),
            telebot.types.BotCommand("post", "Post to channel 🖼"),
            telebot.types.BotCommand("broadcast", "Broadcast message 📢"),
            telebot.types.BotCommand("done", "Notify user about request ✅")
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

def clean_name(text):
    text = re.sub(r'@[a-zA-Z0-9_]+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    clean = re.sub(r'[\.\_\-\[\]\(\)\{\}\:\*\"\'\❖\▶\✅]', ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()

# --- 🎥 File Indexing (Smarter Storage) ---
@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    s_match = re.search(r'(?i)(?:season|s)\s*[:\-]?\s*(\d+)', raw_text)
    e_match = re.search(r'(?i)(?:episode|ep|e)\s*[:\-]?\s*(\d+)', raw_text)
    s_num = int(s_match.group(1)) if s_match else 1
    e_num = int(e_match.group(1)) if e_match else None
    
    title_part = re.split(r'(?i)season|episode|ep|s\d+', raw_text)[0]
    base_title = clean_name(title_part)
    
    display_name = f"{base_title} S{s_num:02d} E{e_num:02d}" if e_num else base_title
    btn_name = f"📺 Ep {e_num:02d}" if e_num else f"🎬 Watch Now"

    files_col.update_one(
        {"file_id": file_id}, 
        {"$set": {
            "file_name": display_name, 
            "base_title": base_title.lower(),
            "s_num": s_num,
            "e_num": e_num,
            "btn_name": btn_name, 
            "file_id": file_id
        }}, upsert=True)
    bot.reply_to(message, f"✅ Saved: {display_name}")

# --- 🔍 Search Logic (The Heart of V3.0) ---
@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Join our channel first!**\n👉 {CHANNEL_USERNAME}")
        return
    
    query = message.text.lower()
    search_query = query.split(" season")[0].split(" episode")[0].strip()
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Smart Keyword Search
    words = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).split()
    if not words: return
    search_filter = {"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words]}
    db_results = list(files_col.find(search_filter))
    
    tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=en-US"
    try:
        tmdb_res = requests.get(tmdb_url).json()
        if tmdb_res.get('results'):
            item = tmdb_res['results'][0]
            is_movie = item.get('media_type') == 'movie'
            title = item.get('title') or item.get('name')
            poster = f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get('poster_path') else None
            
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10\n\n"
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            
            if not db_results:
                caption += "⚠️ **Note:** Only Hindi Dubbed content is available here. Request below if needed."
                markup.add(telebot.types.InlineKeyboardButton("🙋‍♂️ Request (Hindi Only)", callback_data=f"req_{search_query[:20]}"))
            else:
                if is_movie:
                    caption += "👇 **Click below to watch the movie:**"
                    for f in db_results:
                        markup.add(telebot.types.InlineKeyboardButton("🎬 Watch Now", callback_data=f"file_{f['_id']}"))
                else:
                    caption += "👇 **Select Season:**"
                    seasons = sorted(list(set(f['s_num'] for f in db_results)))
                    btns = [telebot.types.InlineKeyboardButton(f"Season {s}", callback_data=f"list_{search_query[:15]}_{s}") for s in seasons]
                    markup.add(*btns)

            if poster: bot.send_photo(message.chat.id, poster, caption=caption, reply_markup=markup, parse_mode="Markdown")
            else: bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else: bot.reply_to(message, "😔 No results found.")
    except: pass

# --- 🎮 Callback Handler (Dynamic Navigation) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data.split('_')
    
    # 1. Season Click -> Show Episodes
    if data[0] == "list":
        q, s = data[1], int(data[2])
        words = q.split()
        search_filter = {"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words], "s_num": s}
        episodes = list(files_col.find(search_filter).sort("e_num", 1))
        
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        btns = [telebot.types.InlineKeyboardButton(f"E{f['e_num']:02d}" if f['e_num'] else "View", callback_data=f"file_{f['_id']}") for f in episodes]
        markup.add(*btns)
        markup.row(telebot.types.InlineKeyboardButton("📥 All Episodes", callback_data=f"all_{q}_{s}"))
        markup.row(telebot.types.InlineKeyboardButton("🔙 Back to Seasons", callback_data=f"back_{q}"))
        
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                 caption=f"📂 **Season {s} Episodes:**\nSelect an episode to download.", reply_markup=markup, parse_mode="Markdown")

    # 2. Back to Seasons
    elif data[0] == "back":
        q = data[1]
        words = q.split()
        search_filter = {"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words]}
        db_results = list(files_col.find(search_filter))
        seasons = sorted(list(set(f['s_num'] for f in db_results)))
        
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btns = [telebot.types.InlineKeyboardButton(f"Season {s}", callback_data=f"list_{q}_{s}") for s in seasons]
        markup.add(*btns)
        
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                 caption="👇 **Select Season:**", reply_markup=markup, parse_mode="Markdown")

    # 3. Batch Send All Episodes
    elif data[0] == "all":
        q, s = data[1], int(data[2])
        bot.answer_callback_query(call.id, "🚀 Sending all episodes... Please wait.", show_alert=False)
        words = q.split()
        search_filter = {"$and": [{"base_title": {"$regex": w, "$options": "i"}} for w in words], "s_num": s}
        episodes = list(files_col.find(search_filter).sort("e_num", 1))
        for f in episodes:
            bot.send_document(call.message.chat.id, f['file_id'], caption=f"🎬 **{f['file_name']}**")
            time.sleep(1) # Prevent flooding

    # 4. Single File Click
    elif data[0] == "file":
        file_data = files_col.find_one({"_id": ObjectId(data[1])})
        if file_data:
            bot.send_document(call.message.chat.id, file_data['file_id'], caption=f"🎬 **{file_data['file_name']}**\n\n🍿 Enjoy! Powered by @RAnimeTV")

    elif data[0] == "req":
        bot.send_message(ADMIN_ID, f"🔔 **New Request:**\nUser: `{call.message.chat.id}`\nTitle: {data[1]}")
        bot.answer_callback_query(call.id, "✅ Request sent to Admin!", show_alert=True)

# --- Keep Alive ---
@app.route('/')
def index(): return "🚀 V3.0 Pro Active!"

def run_bot():
    set_bot_commands()
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
