import telebot
import requests
import threading
import time
import os
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

# আপনার চাবিগুলো
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
    bot.reply_to(message, "স্বাগতম! 🎬\nআমি আপনার প্রো মুভি বট। মুভির নাম লিখুন, আমি ফাইল দিয়ে দেব।")

@bot.message_handler(content_types=['video', 'document'])
def index_files(message):
    if message.chat.id != ADMIN_ID: return
    file_name = message.caption if message.caption else (message.document.file_name if message.document else "Unknown")
    file_id = message.video.file_id if message.video else message.document.file_id
    files_col.update_one({"file_name": file_name}, {"$set": {"file_id": file_id}}, upsert=True)
    bot.reply_to(message, f"✅ ফাইল সেভ হয়েছে!\nনাম: {file_name}")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID or not message.reply_to_message: return
    bot.reply_to(message, "🚀 ব্রডকাস্ট শুরু হয়েছে...")
    for user in users_col.find():
        try: bot.copy_message(user['user_id'], message.chat.id, message.reply_to_message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ ব্রডকাস্ট সফল হয়েছে!")

@bot.message_handler(commands=['top'])
def show_top_searches(message):
    if message.chat.id != ADMIN_ID: return
    msg = "🏆 **Top 10 Searches:**\n"
    for idx, search in enumerate(searches_col.find().sort("count", -1).limit(10), 1):
        msg += f"{idx}. {search['query'].title()} - {search['count']} বার\n"
    bot.reply_to(message, msg)

@bot.message_handler(func=lambda message: True)
def search_logic(message):
    query = message.text.lower()
    search_query = query.split(" season")[0].split(" episode")[0].split(" s0")[0].strip()
    searches_col.update_one({"query": search_query}, {"$inc": {"count": 1}}, upsert=True)
    
    bot.send_chat_action(message.chat.id, 'typing')
    tmdb_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={search_query}&language=en-US"
    
    try:
        tmdb_res = requests.get(tmdb_url).json()
        db_results = list(files_col.find({"file_name": {"$regex": query, "$options": "i"}}))
        
        if tmdb_res.get('results'):
            item = tmdb_res['results'][0]
            title = item.get('title') or item.get('name')
            caption = f"🎬 **Title:** {title}\n⭐ **Rating:** {item.get('vote_average', 'N/A')}/10"
            
            markup = telebot.types.InlineKeyboardMarkup()
            if db_results:
                for file in db_results:
                    markup.add(telebot.types.InlineKeyboardButton(f"📥 {file['file_name']}", callback_data=str(file['_id'])))
            else:
                markup.add(telebot.types.InlineKeyboardButton("🚫 ফাইল এখনো আপলোড করা হয়নি", callback_data="none"))

            poster_path = item.get('poster_path')
            if poster_path:
                bot.send_photo(message.chat.id, f"https://image.tmdb.org/t/p/w500{poster_path}", caption=caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.reply_to(message, "দুঃখিত 😔, এই নামে আমি কিছু খুঁজে পাইনি।")
    except Exception:
        bot.reply_to(message, "একটু সমস্যা হচ্ছে, আবার চেষ্টা করুন!")

@bot.callback_query_handler(func=lambda call: True)
def send_file(call):
    if call.data != "none":
        try:
            file_data = files_col.find_one({"_id": ObjectId(call.data)})
            if file_data: bot.send_document(call.message.chat.id, file_data['file_id'], caption="আপনার ফাইলটি তৈরি! উপভোগ করুন। 🍿")
        except: bot.answer_callback_query(call.id, "লিংকটি কাজ করছে না!", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "ফাইলটি ডাটাবেসে নেই।", show_alert=True)

@app.route('/')
def index():
    return "🚀 Riyaj's Anime Bot is Running 24/7 on Render!"

def run_bot():
    try:
        bot.remove_webhook()
    except:
        pass
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
