import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server V3.4 (Interactive Admin Panel) is Running...")

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
            telebot.types.BotCommand("delete", "Delete wrong files 🗑️"),
            telebot.types.BotCommand("done", "Notify user about request ✅")
        ]
        bot.set_my_commands(admin_cmds, scope=telebot.types.BotCommandScopeChat(ADMIN_ID))
    except: pass

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
    text = re.sub(r'\[.*?\]', ' ', text) 
    text = re.sub(r'@[a-zA-Z0-9_]+', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\(\d{4}\)', ' ', text)
    junk_words = r'(?i)(title|1080p|720p|480p|hevc|10bit|amzn|web-?dl|bluray|brrip|hindi audio|hindi dub|dual audio|esub|mkv|mp4|full movie|in official|official)'
    text = re.sub(junk_words, ' ', text)
    clean = re.sub(r'[^a-zA-Z0-9]', ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()

# ==========================================
# 1. COMMAND HANDLERS
# ==========================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    users_col.update_one({"user_id": message.chat.id}, {"$set": {"user_id": message.chat.id}}, upsert=True)
    text_parts = message.text.split()
    if len(text_parts) > 1:
        query = " ".join(text_parts[1:]).replace("_", " ")
        message.text = query 
        search_logic(message)
        return
    bot.reply_to(message, "Welcome! 🎬\nI am your Ultimate Movie Bot. Send me the name of any anime, movie, or series.")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id != ADMIN_ID: return
    bot.reply_to(message, f"📊 **Admin Dashboard:**\n👥 Total Users: {users_col.count_documents({})}\n🎬 Total Files: {files_col.count_documents({})}", parse_mode="Markdown")

# 🗑️ INTERACTIVE DELETE MENU (Idea 2)
@bot.message_handler(commands=['delete'])
def show_delete_menu(message):
    if message.chat.id != ADMIN_ID: return
    try:
        all_files = files_col.find()
        unique_movies = {}
        for f in all_files:
            compare_key = f.get('base_title', '').lower()
            if compare_key and compare_key not in unique_movies: 
                unique_movies[compare_key] = f.get('base_title', '').title()
        
        if not unique_movies:
            bot.reply_to(message, "🚫 ডিলিট করার মতো কোনো মুভি ডাটাবেসে নেই।")
            return

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for key, name in unique_movies.items():
            markup.add(telebot.types.InlineKeyboardButton(f"🗑️ Delete: {name}", callback_data=f"askdel_{key[:20]}"))
        
        bot.send_message(message.chat.id, "❌ **Admin Delete Panel**\nনিচের কোন মুভিটি ডাটাবেস থেকে সরাতে চান? বাটনে ক্লিক করুন।", reply_markup=markup, parse_mode="Markdown")
    except: pass

@bot.message_handler(commands=['post'])
def custom_channel_post(message):
    if message.chat.id != ADMIN_ID: return
    try:
        content = message.text.replace('/post ', '').split('|')
        name, eps = content[0].strip(), content[1].strip() if len(content) > 1 else "New Release"
        deep_link = get_deep_link(name)
        post_text = f"🎬 **New Release Available!**\n\n📌 **Title:** {name}\n▶️ **Info:** {eps}\n\n👇 **Download or Watch Online:**\n👉 **[Click Here to Watch]({deep_link})**"
        
        tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=en-US"
        res = requests.get(tmdb_url).json()
        poster = f"https://image.tmdb.org/t/p/w500{res['results'][0]['poster_path']}" if res.get('results') and res['results'][0].get('poster_path') else None
        
        if poster: bot.send_photo(CHANNEL_USERNAME, poster, caption=post_text, parse_mode="Markdown")
        else: bot.send_message(CHANNEL_USERNAME, post_text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, "✅ Posted successfully!")
    except: pass

@bot.message_handler(commands=['list', 'menu'])
def show_catalog(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Join our channel first!**\n👉 {CHANNEL_USERNAME}")
        return
    try:
        all_files = files_col.find()
        unique_movies = {}
        for f in all_files:
            key = f.get('base_title', '').lower()
            if key and key not in unique_movies: unique_movies[key] = f.get('base_title', '').title()
        
        if not unique_movies:
            bot.reply_to(message, "🚫 No movies uploaded yet.")
            return
            
        catalog_text = "📚 **Our Complete Collection:**\n\n"
        for m in sorted(unique_movies.values()): catalog_text += f"🍿 **[{m}]({get_deep_link(m)})**\n"
        bot.send_message(message.chat.id, catalog_text, parse_mode="Markdown", disable_web_page_preview=True)
    except: pass

# ==========================================
# 2. FILE UPLOAD & SEARCH
# ==========================================

@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    s_m, e_m = re.search(r'(?i)s\s*[:\-]?\s*(\d+)', raw_text), re.search(r'(?i)e\s*[:\-]?\s*(\d+)', raw_text)
    s_num, e_num = int(s_m.group(1)) if s_m else 1, int(e_m.group(1)) if e_m else None
    
    base_title = clean_name(re.split(r'(?i)season|episode|ep|s\d+', raw_text)[0])
    display_name = f"{base_title.title()} S{s_num:02d} E{e_num:02d}" if e_num else base_title.title()

    files_col.update_one({"file_id": file_id}, {"$set": {"file_name": display_name, "base_title": base_title.lower(), "s_num": s_num, "e_num": e_num, "file_id": file_id}}, upsert=True)
    bot.reply_to(message, f"✅ Cleaned & Saved: {display_name}")

@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Join our channel first!**\n👉 {CHANNEL_USERNAME}")
        return
    query = message.text.lower()
    words = re.sub(r'[^a-zA-Z0-9\s]', ' ', query).split()
    if not words: return
    
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
# 3. CALLBACK HANDLER (DYNAMIC UI)
# ==========================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data.split('_')
    
    # --- DELETE CONFIRMATION SYSTEM ---
    if data[0] == "askdel":
        key = data[1]
        count = files_col.count_documents({"base_title": {"$regex": key, "$options": "i"}})
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("✅ Yes, Delete", callback_data=f"finaldel_{key}"), 
                   telebot.types.InlineKeyboardButton("❌ No, Cancel", callback_data="cancel"))
        bot.edit_message_text(f"⚠️ **পাবলিক কনফার্মেশন!**\nআপনি কি নিশ্চিত যে আপনি '{key.title()}' মুভিটি সরাতে চান? এটি ডাটাবেস থেকে {count} টি ফাইল ডিলিট করবে।", 
                              call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif data[0] == "finaldel":
        key = data[1]
        result = files_col.delete_many({"base_title": {"$regex": key, "$options": "i"}})
        bot.edit_message_text(f"✅ **সাকসেস!** ডাটাবেস থেকে '{key.title()}' এর {result.deleted_count} টি ফাইল চিরতরে মুছে ফেলা হয়েছে।", call.message.chat.id, call.message.message_id)

    elif data[0] == "cancel":
        bot.edit_message_text("❌ ডিলিট প্রসেস বাতিল করা হয়েছে।", call.message.chat.id, call.message.message_id)

    # --- REGULAR FEATURES ---
    elif data[0] == "list":
        q, s = data[1], int(data[2])
        episodes = list(files_col.find({"base_title": {"$regex": q, "$options": "i"}, "s_num": s}).sort("e_num", 1))
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        markup.add(*[telebot.types.InlineKeyboardButton(f"E{f['e_num']:02d}", callback_data=f"file_{f['_id']}") for f in episodes if f['e_num']])
        markup.row(telebot.types.InlineKeyboardButton("📥 All Episodes", callback_data=f"all_{q}_{s}"), 
                   telebot.types.InlineKeyboardButton("🔙 Back", callback_data=f"back_{q}"))
        bot.edit_message_caption(f"📂 **Season {s} Episodes:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data[0] == "back":
        db_res = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}}))
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        markup.add(*[telebot.types.InlineKeyboardButton(f"Season {s}", callback_data=f"list_{data[1]}_{s}") for s in sorted(list(set(f['s_num'] for f in db_res)))])
        bot.edit_message_caption("👇 **Select Season:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data[0] == "all":
        eps = list(files_col.find({"base_title": {"$regex": data[1], "$options": "i"}, "s_num": int(data[2])}).sort("e_num", 1))
        for f in eps: bot.send_document(call.message.chat.id, f['file_id'], caption=f"🎬 **{f['file_name']}**")
        bot.answer_callback_query(call.id, "🚀 All episodes sent!")

    elif data[0] == "file":
        f = files_col.find_one({"_id": ObjectId(data[1])})
        if f: bot.send_document(call.message.chat.id, f['file_id'], caption=f"🎬 **{f['file_name']}**\n🍿 Powered by @RAnimeTV")

@app.route('/')
def index(): return "🚀 V3.4 Pro Active!"

def run_bot():
    set_bot_commands()
    try: bot.remove_webhook()
    except: pass
    bot.infinity_polling(timeout=60)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
