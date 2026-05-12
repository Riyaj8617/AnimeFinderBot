import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server V2.3 (With Dynamic Menu) is Running...")

# --- ক্রেডেনশিয়ালস ---
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

# --- 🛠 স্মার্ট মেনু শর্টকাট সেট করা ---
def set_bot_commands():
    try:
        # সাধারণ ইউজারদের জন্য মেনু
        user_cmds = [
            telebot.types.BotCommand("start", "বট শুরু করুন 🚀"),
            telebot.types.BotCommand("list", "সব মুভি কালেকশন দেখুন 📚"),
            telebot.types.BotCommand("menu", "মেনু ওপেন করুন 📱")
        ]
        bot.set_my_commands(user_cmds)

        # শুধুমাত্র আপনার (Admin) জন্য মেনু
        admin_cmds = [
            telebot.types.BotCommand("start", "বট শুরু করুন 🚀"),
            telebot.types.BotCommand("list", "সব মুভি কালেকশন দেখুন 📚"),
            telebot.types.BotCommand("stats", "বট ড্যাশবোর্ড দেখুন 📊"),
            telebot.types.BotCommand("post", "চ্যানেলে ছবিসহ পোস্ট 🖼"),
            telebot.types.BotCommand("broadcast", "সবাইকে মেসেজ দিন 📢"),
            telebot.types.BotCommand("done", "রিকোয়েস্ট পূরণ নোটিফিকেশন ✅")
        ]
        bot.set_my_commands(admin_cmds, scope=telebot.types.BotCommandScopeChat(ADMIN_ID))
        print("✅ কমান্ড মেনু সফলভাবে সেট করা হয়েছে!")
    except Exception as e:
        print(f"❌ মেনু সেট করতে সমস্যা: {e}")

# --- ম্যাজিক লিংক জেনারেটর ---
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
    bot.reply_to(message, "স্বাগতম! 🎬\nআমি আপনার প্রো মুভি বট। মুভি বা সিরিজের নাম লিখুন, আমি ফাইল দিয়ে দেব।")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id != ADMIN_ID: return
    bot.reply_to(message, f"📊 **ড্যাশবোর্ড:**\n👥 ইউজার: {users_col.count_documents({})}\n🎬 ফাইল: {files_col.count_documents({})}", parse_mode="Markdown")

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
    bot.reply_to(message, f"✅ সেভ হয়েছে: {btn_name}")

@bot.message_handler(commands=['post'])
def custom_channel_post(message):
    if message.chat.id != ADMIN_ID: return
    try:
        content = message.text.replace('/post ', '').split('|')
        name = content[0].strip()
        eps = content[1].strip() if len(content) > 1 else "New Episodes Added"
        deep_link = get_deep_link(name)
        post_text = f"🎬 **নতুন আপলোড চলে এসেছে!**\n\n📌 **নাম:** {name}\n▶️ **এপিসোড:** {eps}\n\n👇 **এক ক্লিকে ডাউনলোড করুন বা দেখুন:**\n👉 **[এখানে ক্লিক করুন]({deep_link})**"
        
        tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&language=en-US"
        poster_url = None
        try:
            res = requests.get(tmdb_url).json()
            if res.get('results') and res['results'][0].get('poster_path'):
                poster_url = f"https://image.tmdb.org/t/p/w500{res['results'][0]['poster_path']}"
        except: pass

        if poster_url: bot.send_photo(CHANNEL_USERNAME, poster_url, caption=post_text, parse_mode="Markdown")
        else: bot.send_message(CHANNEL_USERNAME, post_text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, "✅ চ্যানেলে ছবিসহ পোস্ট করা হয়েছে!")
    except: bot.reply_to(message, "⚠️ ফরম্যাট: `/post মুভির নাম | S01 E01-E12`")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID or not message.reply_to_message: return
    movie_name = message.text.replace('/broadcast', '').strip()
    bot.reply_to(message, "🚀 ব্রডকাস্ট শুরু হয়েছে...")
    for user in users_col.find():
        try:
            if movie_name and message.reply_to_message.content_type == 'photo':
                deep_link = get_deep_link(movie_name)
                caption = f"🎬 **নতুন রিলিজ!**\n\n📌 **নাম:** {movie_name}\n\n👇 **ক্লিক করে এখনই দেখুন:**\n👉 **[{movie_name}]({deep_link})**"
                bot.send_photo(user['user_id'], message.reply_to_message.photo[-1].file_id, caption=caption, parse_mode="Markdown")
            else: bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ ব্রডকাস্ট সফল হয়েছে!")

@bot.message_handler(commands=['done'])
def notify_user(message):
    if message.chat.id != ADMIN_ID: return
    try:
        parts = message.text.split(' ', 2)
        user_id = int(parts[1])
        movie_name = parts[2]
        deep_link = get_deep_link(movie_name)
        noti_text = f"🎉 **সুখবর!**\n\nআপনি যে **{movie_name}** রিকোয়েস্ট করেছিলেন, সেটি আপলোড করা হয়েছে!\n\n👇 এক ক্লিকে এখনই দেখুন:\n👉 **[এখানে ক্লিক করুন]({deep_link})**"
        bot.send_message(user_id, noti_text, parse_mode="Markdown")
        bot.reply_to(message, "✅ ইউজারকে জানানো হয়েছে!")
    except: bot.reply_to(message, "⚠️ ফরম্যাট: `/done UserID মুভির নাম`")

@bot.message_handler(commands=['list', 'menu'])
def show_catalog(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **আগে চ্যানেলে জয়েন করুন!**\n👉 {CHANNEL_USERNAME}")
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
            bot.reply_to(message, "🚫 কোনো মুভি নেই।")
            return
        catalog_text = "📚 **আমাদের কালেকশন:**\n\n"
        for m in sorted(unique_movies.values()):
            catalog_text += f"🍿 **[{m}]({get_deep_link(m)})**\n"
        bot.send_message(message.chat.id, catalog_text, parse_mode="Markdown", disable_web_page_preview=True)
    except: pass

@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **আগে চ্যানেলে জয়েন করুন!**\n👉 {CHANNEL_USERNAME}")
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
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10"
            markup = telebot.types.InlineKeyboardMarkup(row_width=2) 
            buttons = [telebot.types.InlineKeyboardButton(f.get('btn_name', f"📥 {f['file_name'][:15]}"), callback_data=str(f['_id'])) for f in db_results] if db_results else [telebot.types.InlineKeyboardButton("🙋‍♂️ রিকোয়েস্ট করুন", callback_data=f"req_{search_query[:20]}")]
            markup.add(*buttons)
            poster_path = item.get('poster_path')
            if poster_path: bot.send_photo(message.chat.id, f"https://image.tmdb.org/t/p/w500{poster_path}", caption=caption, reply_markup=markup, parse_mode="Markdown")
            else: bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else: bot.reply_to(message, "😔 কিছু খুঁজে পাইনি।")
    except: pass

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith("req_"):
        bot.send_message(ADMIN_ID, f"🔔 **নতুন রিকোয়েস্ট:**\nID: `{call.message.chat.id}`\nমুভি: {call.data.split('_')[1]}")
        bot.answer_callback_query(call.id, "✅ রিকোয়েস্ট পাঠানো হয়েছে!", show_alert=True)
    elif call.data != "none":
        try:
            file_data = files_col.find_one({"_id": ObjectId(call.data)})
            if file_data: bot.send_document(call.message.chat.id, file_data['file_id'], caption=f"🎬 **{file_data['file_name']}**\n\n🍿 উপভোগ করুন!", parse_mode="Markdown")
        except: bot.answer_callback_query(call.id, "লিংক কাজ করছে না!", show_alert=True)

@app.route('/')
def index(): return "🚀 Riyaj's Pro Bot is Running!"

def run_bot():
    set_bot_commands() # <--- বট চালু হওয়ার সময় মেনু সেট হবে
    try: bot.remove_webhook()
    except: pass
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
