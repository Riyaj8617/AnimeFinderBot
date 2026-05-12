import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Ultimate Pro Server is Running...")

# --- ক্রেডেনশিয়ালস ---
BOT_TOKEN = '8351560947:AAEuuIpuOqU9rLJpwJfVrudwsrGNW-iXUWA'
TMDB_API_KEY = 'eac1f699fd04bfed4063efc4e9166925'
MONGO_URI = 'mongodb+srv://riya8617:Riyaj%40786@cluster0.lhmz2q8.mongodb.net/?appName=Cluster0'
ADMIN_ID = 7141977665 
CHANNEL_USERNAME = '@RAnimeTV' # আপনার চ্যানেলের ইউজারনেম

client = MongoClient(MONGO_URI)
db = client['RiyajMovieBot']
files_col = db['files']
users_col = db['users']       
searches_col = db['searches'] 

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Force Subscribe চেকার ---
def is_subscribed(user_id):
    if user_id == ADMIN_ID: return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except:
        return False

@bot.message_handler(commands=['start'])
def send_welcome(message):
    users_col.update_one({"user_id": message.chat.id}, {"$set": {"user_id": message.chat.id}}, upsert=True)
    bot.reply_to(message, "স্বাগতম! 🎬\nআমি আপনার প্রো মুভি বট। মুভি বা সিরিজের নাম লিখুন, আমি ফাইল দিয়ে দেব।")

# --- 📊 Admin Dashboard ---
@bot.message_handler(commands=['stats'])
def show_stats(message):
    if message.chat.id != ADMIN_ID: return
    total_users = users_col.count_documents({})
    total_files = files_col.count_documents({})
    stat_text = f"📊 **বট ড্যাশবোর্ড:**\n\n👥 মোট ইউজার: {total_users} জন\n🎬 মোট আপলোড করা ফাইল: {total_files} টি\n🚀 সার্ভার স্ট্যাটাস: 100% Live"
    bot.reply_to(message, stat_text)

# --- 🎥 ফাইল ইনডেক্সিং এবং অটো-পোস্ট ---
@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    # সিজন এবং এপিসোড নম্বর খোঁজা
    s_match = re.search(r'(?i)(?:season|s)\s*[:\-]?\s*(\d+)', raw_text)
    e_match = re.search(r'(?i)(?:episode|ep|e)\s*[:\-]?\s*(\d+)', raw_text)
    s_num = int(s_match.group(1)) if s_match else None
    e_num = int(e_match.group(1)) if e_match else None
    
    # নাম ক্লিন করা (অন্য চ্যানেলের নাম এবং ব্র্যাকেট সরানো)
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

    files_col.update_one(
        {"file_id": file_id}, 
        {"$set": {"file_name": display_name, "btn_name": btn_name, "file_id": file_id}}, 
        upsert=True
    )
    bot.reply_to(message, f"✅ স্মার্ট অটো-সেভ সম্পন্ন!\nবাটনে দেখাবে: {btn_name}")
    
    # --- 📢 Auto-Post (চ্যানেলে স্বয়ংক্রিয় পোস্ট) ---
    try:
        post_text = f"🎬 **নতুন আপলোড চলে এসেছে!**\n\n📌 **নাম:** {display_name}\n\n👇 আমাদের বটে গিয়ে এখনই ডাউনলোড করুন বা দেখুন!\n👉 @RiyajFinderBot"
        bot.send_message(CHANNEL_USERNAME, post_text, parse_mode="Markdown")
    except: pass

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID or not message.reply_to_message: return
    bot.reply_to(message, "🚀 ব্রডকাস্ট শুরু হয়েছে...")
    for user in users_col.find():
        try: bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ ব্রডকাস্ট সফল হয়েছে!")

# --- 📚 মুভি ক্যাটালগ ---
@bot.message_handler(commands=['list', 'menu'])
def show_catalog(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **আগে আমাদের চ্যানেলে জয়েন করুন!**\n\nমুভি দেখতে হলে অবশ্যই চ্যানেলে জয়েন থাকতে হবে।\n\n👉 **চ্যানেল:** {CHANNEL_USERNAME}\n\nজয়েন করার পর আবার /list লিখুন।")
        return
        
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        all_files = files_col.find()
        unique_movies = set()
        for f in all_files:
            name = re.split(r'(?i) S\d+| Ep \d+', f.get('file_name', ''))[0].strip()
            if name: unique_movies.add(name)
            
        if not unique_movies:
            bot.reply_to(message, "🚫 এখনো কোনো মুভি আপলোড করা হয়নি।")
            return
            
        catalog_text = "📚 **আমাদের কালেকশন:**\n\n" + "\n".join([f"🍿 **{m}**" for m in sorted(unique_movies)])
        catalog_text += "\n\n💡 *নাম লিখে সার্চ করলে সব ফাইল পেয়ে যাবেন!*"
        bot.send_message(message.chat.id, catalog_text, parse_mode="Markdown")
    except: pass

# --- 🔍 সার্চ লজিক ---
@bot.message_handler(func=lambda message: True)
def search_logic(message):
    if not is_subscribed(message.chat.id):
        bot.reply_to(message, f"❌ **আগে আমাদের চ্যানেলে জয়েন করুন!**\n\nডাউনলোড করতে হলে অবশ্যই চ্যানেলে জয়েন থাকতে হবে।\n\n👉 **চ্যানেল:** {CHANNEL_USERNAME}")
        return

    query = message.text.lower()
    search_query = query.split(" season")[0].split(" episode")[0].split(" s0")[0].strip()
    searches_col.update_one({"query": search_query}, {"$inc": {"count": 1}}, upsert=True)
    
    bot.send_chat_action(message.chat.id, 'typing')
    tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=en-US"
    
    try:
        tmdb_res = requests.get(tmdb_url).json()
        db_results = list(files_col.find({"file_name": {"$regex": search_query, "$options": "i"}}).sort("file_name", 1))
        
        if tmdb_res.get('results'):
            item = tmdb_res['results'][0]
            title = item.get('title') or item.get('name')
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10\n\n👇 **আপনার পছন্দের এপিসোড সিলেক্ট করুন:**"
            
            markup = telebot.types.InlineKeyboardMarkup(row_width=2) 
            buttons = []
            if db_results:
                for file in db_results:
                    btn_text = file.get('btn_name', f"📥 {file['file_name'][:15]}")
                    buttons.append(telebot.types.InlineKeyboardButton(btn_text, callback_data=str(file['_id'])))
                markup.add(*buttons)
            else:
                markup.add(telebot.types.InlineKeyboardButton("🙋‍♂️ মুভিটি রিকোয়েস্ট করুন", callback_data=f"req_{search_query[:20]}"))

            poster_path = item.get('poster_path')
            if poster_path:
                bot.send_photo(message.chat.id, f"https://image.tmdb.org/t/p/w500{poster_path}", caption=caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.reply_to(message, "দুঃখিত 😔, কিছু খুঁজে পাইনি।")
    except: pass

# --- 📥 ফাইল পাঠানো এবং রিকোয়েস্ট হ্যান্ডলিং ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith("req_"):
        bot.send_message(ADMIN_ID, f"🔔 **নতুন মুভি রিকোয়েস্ট:**\nইউজার: `{call.message.chat.id}`\nনাম: {call.data.split('_')[1]}")
        bot.answer_callback_query(call.id, "✅ আপনার রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে!", show_alert=True)
        return

    if call.data != "none":
        try:
            file_data = files_col.find_one({"_id": ObjectId(call.data)})
            if file_data:
                file_title = file_data.get('file_name', 'Unknown File')
                bot.send_document(call.message.chat.id, file_data['file_id'], caption=f"🎬 **{file_title}**\n\n🍿 আপনার ফাইলটি তৈরি! উপভোগ করুন।", parse_mode="Markdown")
        except: bot.answer_callback_query(call.id, "লিংকটি কাজ করছে না!", show_alert=True)
    else: bot.answer_callback_query(call.id, "ফাইলটি ডাটাবেসে নেই।", show_alert=True)

@app.route('/')
def index():
    return "🚀 Riyaj's Ultimate Pro Bot is Running 24/7!"

def run_bot():
    try: bot.remove_webhook()
    except: pass
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
