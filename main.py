import os
import re
import logging
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB Setup
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("❌ MONGO_URL is missing!")
    exit(1)

try:
    client = MongoClient(MONGO_URL)
    db = client['filter_bot']
    filters_collection = db['filters']
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")
    exit(1)

# Extract buttons from text
def extract_buttons(text):
    if not text: return text, []
    pattern = r'\[([^\]]+)\]\(buttonurl:([^)]+)\)'
    buttons = re.findall(pattern, text)
    clean_text = re.sub(pattern, '', text).strip()
    return clean_text, buttons

# Build button markup
def build_buttons(buttons):
    if not buttons:
        return None
    keyboard = [[InlineKeyboardButton(name, url=url)] for name, url in buttons]
    return InlineKeyboardMarkup(keyboard)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm a Global Manual Filter Bot\n\n"
        "Commands:\n"
        "/add_filter <keyword> - Reply to a message to save it as filter\n"
        "/del_filter <keyword> - Delete a filter\n"
        "/filters - Show all saved filters"
    )

# Add filter
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to a message to save as filter!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /add_filter <keyword>")
        return
    
    keyword = context.args[0].lower()
    replied_msg = update.message.reply_to_message
    chat_id = update.effective_chat.id
    
    # Extract content
    filter_data = {
        'chat_id': chat_id,
        'keyword': keyword,
        'text': None,
        'file_id': None,
        'file_type': None,
        'caption': None,
        'buttons': []
    }
    
    # Check for additional buttons in command
    command_text = update.message.text.split(None, 1)[1] if len(update.message.text.split()) > 1 else ""
    # Remove keyword from command text to get potential button text
    potential_button_text = command_text.replace(keyword, "", 1).strip()
    _, cmd_buttons = extract_buttons(potential_button_text)
    
    # Handle different message types
    if replied_msg.text:
        clean_text, msg_buttons = extract_buttons(replied_msg.text_html)
        filter_data['text'] = clean_text
        filter_data['buttons'] = cmd_buttons if cmd_buttons else msg_buttons
    elif replied_msg.caption:
        clean_caption, msg_buttons = extract_buttons(replied_msg.caption_html)
        filter_data['caption'] = clean_caption
        filter_data['buttons'] = cmd_buttons if cmd_buttons else msg_buttons
    
    # Handle media
    if replied_msg.photo:
        filter_data['file_id'] = replied_msg.photo[-1].file_id
        filter_data['file_type'] = 'photo'
    elif replied_msg.video:
        filter_data['file_id'] = replied_msg.video.file_id
        filter_data['file_type'] = 'video'
    elif replied_msg.document:
        filter_data['file_id'] = replied_msg.document.file_id
        filter_data['file_type'] = 'document'
    elif replied_msg.animation:
        filter_data['file_id'] = replied_msg.animation.file_id
        filter_data['file_type'] = 'animation'
    elif replied_msg.sticker:
        filter_data['file_id'] = replied_msg.sticker.file_id
        filter_data['file_type'] = 'sticker'
    elif replied_msg.audio:
        filter_data['file_id'] = replied_msg.audio.file_id
        filter_data['file_type'] = 'audio'
    elif replied_msg.voice:
        filter_data['file_id'] = replied_msg.voice.file_id
        filter_data['file_type'] = 'voice'
    
    # Save to database (replace if exists)
    filters_collection.replace_one(
        {'chat_id': chat_id, 'keyword': keyword},
        filter_data,
        upsert=True
    )
    
    await update.message.reply_text(f"✅ Filter saved for keyword: {keyword}")

# Delete filter
async def del_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /del_filter <keyword>")
        return
    
    keyword = context.args[0].lower()
    chat_id = update.effective_chat.id
    
    result = filters_collection.delete_one({'chat_id': chat_id, 'keyword': keyword})
    
    if result.deleted_count > 0:
        await update.message.reply_text(f"✅ Filter deleted: {keyword}")
    else:
        await update.message.reply_text(f"❌ Filter not found: {keyword}")

# List all filters
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    all_filters = filters_collection.find({'chat_id': chat_id})
    
    keywords = [f['keyword'] for f in all_filters]
    
    if keywords:
        await update.message.reply_text(
            f"📝 Saved Filters ({len(keywords)}):\n\n" + "\n".join(f"• {k}" for k in keywords)
        )
    else:
        await update.message.reply_text("❌ No filters saved yet!")

# Handle text messages (check for filters)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.lower()
    chat_id = update.effective_chat.id
    
    # Check all filters
    # Optimization: In production, use specific query instead of fetching all
    all_filters = filters_collection.find({'chat_id': chat_id})
    
    for filter_doc in all_filters:
        if filter_doc['keyword'] in text:
            reply_markup = build_buttons(filter_doc.get('buttons'))
            
            try:
                # Send appropriate content
                if filter_doc.get('file_type'):
                    send_method = {
                        'photo': context.bot.send_photo,
                        'video': context.bot.send_video,
                        'document': context.bot.send_document,
                        'animation': context.bot.send_animation,
                        'sticker': context.bot.send_sticker,
                        'audio': context.bot.send_audio,
                        'voice': context.bot.send_voice
                    }.get(filter_doc['file_type'])
                    
                    if send_method:
                        kwargs = {
                            'chat_id': chat_id,
                            filter_doc['file_type']: filter_doc['file_id'],
                            'reply_markup': reply_markup,
                            'reply_to_message_id': update.message.message_id
                        }
                        
                        # Sticker doesn't support caption/parse_mode
                        if filter_doc['file_type'] != 'sticker':
                            kwargs['caption'] = filter_doc.get('caption')
                            kwargs['parse_mode'] = ParseMode.HTML
                            
                        await send_method(**kwargs)
                        
                elif filter_doc.get('text'):
                    await update.message.reply_text(
                        filter_doc['text'],
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                        reply_to_message_id=update.message.message_id
                    )
            except Exception as e:
                print(f"Error sending filter: {e}")
            break

# Main function
def main():
    # Updated to get from ENV directly
    BOT_TOKEN = os.getenv("API_TOKEN")
    
    if not BOT_TOKEN:
        print("❌ Please set API_TOKEN environment variable!")
        return
    
    print("🚀 Bot Starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_filter", add_filter))
    app.add_handler(CommandHandler("del_filter", del_filter))
    app.add_handler(CommandHandler("filters", list_filters))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot is running polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
