# -*- coding: utf-8 -*-
"""Handles displaying user statistics and leaderboards."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler # Added missing import
)

# Import necessary components from other modules
try:
    # Corrected Import: Import DB_MANAGER from database.manager
    from config import logger, MAIN_MENU, STATS_MENU, LEADERBOARD_LIMIT
    from database.manager import DB_MANAGER 
    from utils.helpers import safe_send_message, safe_edit_message_text, format_duration
    from handlers.common import main_menu_callback # For returning to main menu
except ImportError as e:
    # Fallback for potential import issues
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.stats: {e}. Using placeholders.")
    # Define placeholders
    MAIN_MENU, STATS_MENU = 0, 8 # Match config.py
    LEADERBOARD_LIMIT = 10
    DB_MANAGER = None # Keep fallback as None
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def format_duration(seconds): logger.warning("Placeholder format_duration called!"); return f"{seconds}s"
    async def main_menu_callback(*args, **kwargs): logger.error("Placeholder main_menu_callback called!"); return MAIN_MENU

# --- Helper Functions --- 

def create_stats_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the main keyboard for the statistics section."""
    keyboard = [
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats_my_stats")],
        [InlineKeyboardButton("🏆 لوحة الصدارة", callback_data="stats_leaderboard")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Steps --- 

async def stats_menu(update: Update, context: CallbackContext) -> int:
    """Displays the main statistics menu."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        logger.info(f"User {user_id} entered stats menu.")
        text = "🏅 اختر الإحصائيات التي تريد عرضها:"
        keyboard = create_stats_menu_keyboard()
        await safe_edit_message_text(query, text=text, reply_markup=keyboard)
    else:
        logger.warning("stats_menu called without callback query.")
        await safe_send_message(context.bot, update.effective_chat.id, text="يرجى استخدام القائمة الرئيسية.")
        return MAIN_MENU
        
    return STATS_MENU # Stay in stats menu state

async def show_my_stats(update: Update, context: CallbackContext) -> int:
    """Fetches and displays the personal statistics for the user."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested personal stats.")

    stats_text = "📊 *إحصائياتي الشخصية*\n\n"
    if DB_MANAGER:
        user_stats = DB_MANAGER.get_user_stats(user_id)
        if user_stats and user_stats.get("total_quizzes_taken", 0) > 0:
            total_time_str = format_duration(user_stats.get("total_time_seconds", 0))
            # Corrected: Ensure keys exist or use .get() with default
            stats_text += f"📝 إجمالي الاختبارات: {user_stats.get(	'total_quizzes_taken	', 0)}\n"
            stats_text += f"✅ مجموع الإجابات الصحيحة: {user_stats.get(	'total_correct	', 0)}\n"
            stats_text += f"❌ مجموع الإجابات الخاطئة: {user_stats.get(	'total_wrong	', 0)}\n"
            stats_text += f"⏭️ مجموع الأسئلة المتخطاة: {user_stats.get(	'total_skipped	', 0)}\n"
            stats_text += f"💯 متوسط النتيجة: {user_stats.get(	'average_score	', 0.0):.1f}%\n"
            stats_text += f"⏱️ إجمالي وقت اللعب: {total_time_str}"
        else:
            stats_text += "لم تقم بإكمال أي اختبارات بعد. ابدأ اختباراً لتظهر إحصائياتك هنا!"
    else:
        stats_text += "عذراً، لا يمكن استرجاع الإحصائيات حالياً (مشكلة في قاعدة البيانات)."

    # Corrected: Removed \n from inside callback_data string
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    await safe_edit_message_text(query, text=stats_text, reply_markup=keyboard, parse_mode="Markdown")
    
    return STATS_MENU # Stay in stats menu state

async def show_leaderboard(update: Update, context: CallbackContext) -> int:
    """Fetches and displays the leaderboard."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested leaderboard.")

    leaderboard_text = f"🏆 *لوحة الصدارة (أفضل {LEADERBOARD_LIMIT} لاعبين)*\n\n"
    rank_emojis = ["🥇", "🥈", "🥉"] + ["🏅"] * (LEADERBOARD_LIMIT - 3)

    if DB_MANAGER:
        leaderboard_data = DB_MANAGER.get_leaderboard(limit=LEADERBOARD_LIMIT)
        if leaderboard_data:
            for i, entry in enumerate(leaderboard_data):
                rank = rank_emojis[i] if i < len(rank_emojis) else f"{i+1}."
                # Corrected: Use .get() for display_name and handle potential missing user_id
                user_id_entry = entry.get(	'user_id	', 	'Unknown	')
                display_name = entry.get("user_display_name", f"User {user_id_entry}")
                # Escape markdown characters in username
                safe_display_name = display_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
                avg_score = entry.get(	'average_score	', 0.0)
                quizzes_taken = entry.get(	'quizzes_taken	', 0)
                leaderboard_text += f"{rank} {safe_display_name} - متوسط: {avg_score:.1f}% ({quizzes_taken} اختبار)\n"
        else:
            leaderboard_text += "لا توجد بيانات كافية لعرض لوحة الصدارة بعد."
    else:
        leaderboard_text += "عذراً، لا يمكن استرجاع لوحة الصدارة حالياً (مشكلة في قاعدة البيانات)."

    # Corrected: Removed \n from inside callback_data string
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة الإحصائيات", callback_data="stats_menu")]])
    await safe_edit_message_text(query, text=leaderboard_text, reply_markup=keyboard, parse_mode="Markdown")
    
    return STATS_MENU # Stay in stats menu state

# --- Conversation Handler Definition --- 

stats_conv_handler = ConversationHandler(
    # Entry point is from the main menu handler when 'menu_stats' is chosen
    entry_points=[CallbackQueryHandler(stats_menu, pattern="^menu_stats$")], 
    states={
        STATS_MENU: [
            CallbackQueryHandler(show_my_stats, pattern="^stats_my_stats$"),
            CallbackQueryHandler(show_leaderboard, pattern="^stats_leaderboard$"),
            # Handler to go back to the stats menu itself (e.g., from leaderboard view)
            CallbackQueryHandler(stats_menu, pattern="^stats_menu$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # Allow returning to main menu
        ],
        # No other states needed for simple stats display
    },
    fallbacks=[
        CommandHandler("start", main_menu_callback), # Go to main menu on /start
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # Handle explicit main menu return
        # Fallback within stats conversation
        CallbackQueryHandler(stats_menu, pattern=".*") # Go back to stats menu on any other callback
    ],
    map_to_parent={
        # If MAIN_MENU is returned, map it to the main conversation handler's MAIN_MENU state
        MAIN_MENU: MAIN_MENU,
        # If END is returned, end the conversation (though not used here)
        # END: END 
    },
    persistent=True, # Enable persistence
    name="stats_conversation" # Unique name for persistence
)

