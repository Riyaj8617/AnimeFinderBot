import telebot
import requests
import threading
import time
import os
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

print("🚀 Pro Server is Running with Smart Auto-Filter...")

BOT_TOKEN = '8351560947:AAEuuIpuOqU9rLJpwJfVrudwsrGNW-iXUWA'
TMDB_API_KEY = 'eac1f699fd04bfed4063efc4e9166925'
MONGO_URI = 'mongodb+srv://riya8617:Riyaj%40786@cluster0.lhmz2q8.mongodb.net/?appName=Cluster0'
ADMIN_ID = 7141977665 

client = MongoClient(MONGO_URI)
db = client['RiyajMovieBot']
files_col = db['files']
users_col = db['users']       
searches_col = db['searches'] 

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    users_col.update_one({"user_id": message.chat.id}, {"$set": {"user_id": message.chat.id}}, upsert=True)
    bot.reply_to(message, "স্বাগতম! 🎬\nআমি আপনার প্রো মুভি বট। মুভি বা সিরিজের নাম লিখুন, আমি ফাইল দিয়ে দেব।")

@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    
    raw_text = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    
    # 🧠 AI Brain: ক্যাপশন থেকে Season এবং Episode খোঁজার কোড
    s_match = re.search(r'(?i)(?:season|s)\s*[:\-]?\s*(\d+)', raw_text)
    e_match = re.search(r'(?i)(?:episode|ep|e)\s*[:\-]?\s*(\d+)', raw_text)
    
    s_num = int(s_match.group(1)) if s_match else None
    e_num = int(e_match.group(1)) if e_match else None
    
    # অপ্রয়োজনীয় চিহ্ন বাদ দিয়ে শুধু আসল নামটা নেওয়া
    title_part = re.split(r'(?i)season|episode|ep|s\d+', raw_text)[0]
    clean_title = title_part.replace('❖', '').replace('▶', '').replace('✅', '').strip()
    
    # বাটনের নাম অটোমেটিক তৈরি করা
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

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID or not message.reply_to_message: return
    bot.reply_to(message, "🚀 ব্রডকাস্ট শুরু হয়েছে...")
    for user in users_col.find():
        try: bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ ব্রডকাস্ট সফল হয়েছে!")
@bot.message_handler(commands=['list', 'menu'])
def show_catalog(message):
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        all_files = files_col.find()
        unique_movies = set()
        
        for file in all_files:
            full_name = file.get('file_name', '')
            # শুধু আসল নামটা বের করা (সিজন বা এপিসোড নম্বর বাদ দিয়ে)
            base_name = re.split(r'(?i) S\d+| Ep \d+', full_name)[0].strip()
            if base_name:
                unique_movies.add(base_name)
                
        if not unique_movies:
            bot.reply_to(message, "🚫 এখনো কোনো মুভি বা সিরিজ আপলোড করা হয়নি।")
            return
            
        catalog_text = "📚 **আমাদের কালেকশনে থাকা মুভি ও অ্যানিমে:**\n\n"
        for idx, movie in enumerate(sorted(unique_movies), 1):
            catalog_text += f"🍿 **{movie}**\n"
            
        catalog_text += "\n💡 *যেকোনো একটির নাম লিখে আমাকে মেসেজ দিন, আমি ছবিসহ সব ফাইল দিয়ে দেব!*"
        bot.send_message(message.chat.id, catalog_text, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, "একটু সমস্যা হচ্ছে, পরে আবার চেষ্টা করুন।")
        



@bot.message_handler(func=lambda message: True)
def search_logic(message):
    query = message.text.lower()
    search_query = query.split(" season")[0].split(" episode")[0].split(" s0")[0].strip()
    searches_col.update_one({"query": search_query}, {"$inc": {"count": 1}}, upsert=True)
    
    bot.send_chat_action(message.chat.id, 'typing')
    tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=en-US"
    
    try:
        tmdb_res = requests.get(tmdb_url).json()
        # ফাইলগুলো Ep 1, Ep 2 অনুযায়ী সাজানো হবে
        db_results = list(files_col.find({"file_name": {"$regex": search_query, "$options": "i"}}).sort("file_name", 1))
        
        if tmdb_res.get('results'):
            item = tmdb_res['results'][0]
            title = item.get('title') or item.get('name')
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10\n\n👇 **আপনার পছন্দের এপিসোড সিলেক্ট করুন:**"
            
            # ২ কলামের সুন্দর গ্রিড ডিজাইন (Netflix স্টাইল)
            markup = telebot.types.InlineKeyboardMarkup(row_width=2) 
            
            buttons = []
            if db_results:
                for file in db_results:
                    btn_text = file.get('btn_name', f"📥 {file['file_name'][:15]}")
                    buttons.append(telebot.types.InlineKeyboardButton(btn_text, callback_data=str(file['_id'])))
                
                markup.add(*buttons)
            else:
                markup.add(telebot.types.InlineKeyboardButton("🚫 এখনো আপলোড করা হয়নি", callback_data="none"))

            poster_path = item.get('poster_path')
            if poster_path:
                bot.send_photo(message.chat.id, f"https://image.tmdb.org/t/p/w500{poster_path}", caption=caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.reply_to(message, "দুঃখিত 😔, এই নামে আমি কিছু খুঁজে পাইনি।")
    except Exception as e:
        bot.reply_to(message, "একটু সমস্যা হচ্ছে, আবার চেষ্টা করুন!")

@bot.callback_query_handler(func=lambda call: True)
def send_file(call):
    if call.data != "none":
        try:
            file_data = files_col.find_one({"_id": ObjectId(call.data)})
            if file_data:
                # ডাইনামিক ক্যাপশন তৈরি করা (ফাইলের আসল নামসহ)
                file_title = file_data.get('file_name', 'Unknown File')
                dynamic_caption = f"🎬 **{file_title}**\n\n🍿 আপনার ফাইলটি তৈরি! উপভোগ করুন।"
                
                bot.send_document(
                    call.message.chat.id, 
                    file_data['file_id'], 
                    caption=dynamic_caption, 
                    parse_mode="Markdown"
                )
        except Exception as e: 
            bot.answer_callback_query(call.id, "লিংকটি কাজ করছে না!", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "ফাইলটি ডাটাবেসে নেই।", show_alert=True)

@app.route('/')
def index():
    return "🚀 Riyaj's Pro Auto-Filter Bot is Running 24/7!"

def run_bot():
    try: bot.remove_webhook()
    except: pass
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
