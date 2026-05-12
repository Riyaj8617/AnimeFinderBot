import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server V2.4 (English Version) is Running...")

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

# --- 🛠 Smart Menu Setup (English) ---
def set_bot_commands():
    try:
        # Commands for normal users
        user_cmds = [
            telebot.types.BotCommand("start", "Start the bot 🚀"),
            telebot.types.BotCommand("list", "View all collections 📚"),
            telebot.types.BotCommand("menu", "Open main menu 📱")
        ]
        bot.set_my_commands(user_cmds)

        # Commands for Admin only
        admin_cmds = [
            telebot.types.BotCommand("start", "Start the bot 🚀"),
            telebot.types.BotCommand("list", "View all collections 📚"),
            telebot.types.BotCommand("stats", "View admin dashboard 📊"),
            telebot.types.BotCommand("post", "Post to channel 🖼"),
            telebot.types.BotCommand("broadcast", "Broadcast message 📢"),
            telebot.types.BotCommand("done", "Notify user about request ✅")
        ]
        bot.set_my_commands(admin_cmds, scope=telebot.types.BotCommandScopeChat(ADMIN_ID))
        print("✅ Bot commands set successfully!")
    except Exception as e:
        print(f"❌ Failed to set commands: {e}")

# --- Magic Link Generator ---
def get_deep_link(movie_name):
    payload = re.sub(r'[^a-zA-Z0-9]', '_', movie_name)[:60]
    return f"https://t.me/{BOT_USERNAME}?start={payload}"

def is_subscribed(user_id):
    if user_id == ADMIN_ID: return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except: return False

@bot.message_handler(commands=['start'])
def send_welcome(message):
    users_col.update_one({"user_id": message.chat.id}, {"$set": {"user_id": message.chat.id}}, upsert=True)
    text_parts = message.text.split()
    if len(text_parts) > 1:
        query = " ".join(text_parts[1:]).replace("_", " ")
        message.text = query 
        search_logic(message)
        return
    bot.reply_to(message, "Welcome! 🎬\nI am your Ultimate Movie Bot. Send me the name of any anime, movie, or series, and I will provide the files instantly.")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id != ADMIN_ID: return
    bot.reply_to(message, f"📊 **Admin Dashboard:**\n👥 Total Users: {users_col.count_documents({})}\n🎬 Total Files: {files_col.count_documents({})}", parse_mode="Markdown")

@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    s_match = re.search(r'(?i)(?:season|s)\s*[:\-]?\s*(\d+)', raw_text)
    e_match = re.search(r'(?i)(?:episode|ep|e)\s*[:\-]?\s*(\d+)', raw_text)
    s_num = int(s_match.group(1)) if s_match else None
    e_num = int(e_match.group(1)) if e_match else None
    
    title_part = re.split(r'(?i)season|episode|ep|s\d+', raw_text)[0]
    title_part = re.sub(r'@[a-zA-Z0-9_]+', '', title_part)
    clean_title = title_part.replace('❖', '').replace('▶', '').replace('✅', '').replace('[', '').replace(']', '').strip()
    
    if s_num and e_num:
        display_name = f"{clean_title} S{s_num:02d} E{e_num:02d}"
        btn_name = f"📺 S{s_num:02d} E{e_num:02d}"
    elif e_num:
        display_name = f"{clean_title} Ep {e_num:02d}"
        btn_name = f"📺 Ep {e_num:02d}"
    else:
        display_name = clean_title[:30]
        btn_name = f"🎬 {display_name[:20]}"

    files_col.update_one({"file_id": file_id}, {"$set": {"file_name": display_name, "btn_name": btn_name, "file_id": file_id}}, upsert=True)
    bot.reply_to(message, f"✅ Successfully saved: {btn_name}")

@bot.message_handler(commands=['post'])
def custom_channel_post(message):
    if message.chat.id != ADMIN_ID: return
    try:
        content = message.text.replace('/post ', '').split('|')
        name = content[0].strip()
        eps = content[1].strip() if len(content) > 1 else "New Episodes Added"
        deep_link = get_deep_link(name)
        post_text = f"🎬 **New Release Available!**\n\n📌 **Title:** {name}\n▶️ **Episodes:** {eps}\n\n👇 **Download or Watch Online:**\n👉 **[Click Here to Watch]({deep_link})**"
        
        tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=en-US"
        poster_url = None
        try:
            res = requests.get(tmdb_url).json()
            if res.get('results') and res['results'][0].get('poster_path'):
                poster_url = f"https://image.tmdb.org/t/p/w500{res['results'][0]['poster_path']}"
        except: pass

        if poster_url: bot.send_photo(CHANNEL_USERNAME, poster_url, caption=post_text, parse_mode="Markdown")
        else: bot.send_message(CHANNEL_USERNAME, post_text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, "✅ Posted to channel successfully!")
    except: bot.reply_to(message, "⚠️ Invalid Format! Please use:\n`/post Movie Name | S01 E01-E12`")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID or not message.reply_to_message: return
    movie_name = message.text.replace('/broadcast', '').strip()
    bot.reply_to(message, "🚀 Broadcasting started...")
    for user in users_col.find():
        try:
            if movie_name and message.reply_to_message.content_type == 'photo':
                deep_link = get_deep_link(movie_name)
                caption = f"🎬 **New Release!**\n\n📌 **Title:** {movie_name}\n\n👇 **Click the link below to watch now:**\n👉 **[{movie_name}]({deep_link})**"
                bot.send_photo(user['user_id'], message.reply_to_message.photo[-1].file_id, caption=caption, parse_mode="Markdown")
            else: bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ Broadcast completed successfully!")

@bot.message_handler(commands=['done'])
def notify_user(message):
    if message.chat.id != ADMIN_ID: return
    try:
        parts = message.text.split(' ', 2)
        user_id = int(parts[1])
        movie_name = parts[2]
        deep_link = get_deep_link(movie_name)
        noti_text = f"🎉 **Great News!**\n\nThe movie **{movie_name}** you requested has been uploaded!\n\n👇 Click below to watch it now:\n👉 **[Click Here to Watch]({deep_link})**"
        bot.send_message(user_id, noti_text, parse_mode="Markdown")
        bot.reply_to(message, "✅ User has been notified successfully!")
    except: bot.reply_to(message, "⚠️ Invalid Format! Please use:\n`/done UserID Movie Name`")

@bot.message_handler(commands=['list', 'menu'])
def show_catalog(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Please join our channel first to use the bot!**\n👉 {CHANNEL_USERNAME}")
        return
    try:
        all_files = files_col.find()
        unique_movies = {}
        for f in all_files:
            raw_name = f.get('file_name', '').replace('[', '').replace(']', '')
            clean_name = re.split(r'(?i) S\d+| Ep \d+', raw_name)[0].strip()
            compare_key = re.sub(r'[^a-zA-Z0-9]', '', clean_name.lower())
            if compare_key and compare_key not in unique_movies: unique_movies[compare_key] = clean_name
        if not unique_movies:
            bot.reply_to(message, "🚫 No movies uploaded yet.")
            return
        catalog_text = "📚 **Our Complete Collection:**\n\n"
        for m in sorted(unique_movies.values()):
            catalog_text += f"🍿 **[{m}]({get_deep_link(m)})**\n"
        catalog_text += "\n💡 *Tap on any name to get the files instantly!*"
        bot.send_message(message.chat.id, catalog_text, parse_mode="Markdown", disable_web_page_preview=True)
    except: pass

@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **Please join our channel first to use the bot!**\n👉 {CHANNEL_USERNAME}")
        return
    query = message.text.lower()
    search_query = query.split(" season")[0].split(" episode")[0].split(" s0")[0].strip()
    searches_col.update_one({"query": search_query}, {"$inc": {"count": 1}}, upsert=True)
    tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=en-US"
    try:
        tmdb_res = requests.get(tmdb_url).json()
        db_results = list(files_col.find({"file_name": {"$regex": search_query, "$options": "i"}}).sort("file_name", 1))
        if tmdb_res.get('results'):
            item = tmdb_res['results'][0]
            title = item.get('title') or item.get('name')
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10\n\n👇 **Select your episode below:**"
            markup = telebot.types.InlineKeyboardMarkup(row_width=2) 
            buttons = [telebot.types.InlineKeyboardButton(f.get('btn_name', f"📥 {f['file_name'][:15]}"), callback_data=str(f['_id'])) for f in db_results] if db_results else [telebot.types.InlineKeyboardButton("🙋‍♂️ Request this Movie", callback_data=f"req_{search_query[:20]}")]
            markup.add(*buttons)
            poster_path = item.get('poster_path')
            if poster_path: bot.send_photo(message.chat.id, f"https://image.tmdb.org/t/p/w500{poster_path}", caption=caption, reply_markup=markup, parse_mode="Markdown")
            else: bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else: bot.reply_to(message, "😔 Sorry, couldn't find anything matching your query.")
    except: pass

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith("req_"):
        bot.send_message(ADMIN_ID, f"🔔 **New Movie Request:**\nUser ID: `{call.message.chat.id}`\nTitle: {call.data.split('_')[1]}")
        bot.answer_callback_query(call.id, "✅ Your request has been sent to the Admin!", show_alert=True)
    elif call.data != "none":
        try:
            file_data = files_col.find_one({"_id": ObjectId(call.data)})
            if file_data: bot.send_document(call.message.chat.id, file_data['file_id'], caption=f"🎬 **{file_data['file_name']}**\n\n🍿 Enjoy your movie! Powered by @RAnimeTV", parse_mode="Markdown")
        except: bot.answer_callback_query(call.id, "⚠️ This link is no longer valid!", show_alert=True)

@app.route('/')
def index(): return "🚀 Riyaj's Pro Bot is Running in English!"

def run_bot():
    set_bot_commands() 
    try: bot.remove_webhook()
    except: pass
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
