"""
admin_interface.py (v9 - Fix filter parsing and all_time/all consistency)

Handles the admin statistics dashboard interface, including command handling,
callback queries for menu navigation, and fetching/displaying statistics.

This version fixes the parsing of callback data for time filters, especially
ensuring that 'all_time' is correctly identified and passed. It also aims
to ensure consistent use of 'all_time' as the key when interacting with
the data layer.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import telegram.error # Import for specific error handling
import os

from utils.admin_auth import is_admin as is_admin_original # Renamed to avoid conflict
from database.manager import DB_MANAGER
from config import logger

# Assuming process_arabic_text is correctly defined in admin_dashboard_display
# and handles Arabic text reshaping and bidi for proper display.
from .admin_dashboard_display import (
    get_usage_overview_display,
    get_quiz_performance_display,
    get_user_interaction_display,
    get_question_stats_display,
    TIME_FILTERS_DISPLAY, # This should use 'all_time' as a key internally if that's what manager expects
    process_arabic_text
)

STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"

logger.info("[AdminInterfaceV9_FilterFix] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV9_FilterFix] is_admin: No effective_user found.")
        return False
    user_id = user.id
    logger.info(f"[AdminInterfaceV9_FilterFix] is_admin: Checking admin for user_id: {user_id}")
    if hasattr(DB_MANAGER, 'is_user_admin'):
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            logger.info(f"[AdminInterfaceV9_FilterFix] is_admin: DB_MANAGER returned {admin_status} for {user_id}")
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV9_FilterFix] is_admin: DB_MANAGER error for {user_id}: {e}", exc_info=True)
            return False
    logger.warning(f"[AdminInterfaceV9_FilterFix] is_admin: DB_MANAGER.is_user_admin not found. Defaulting to False for {user_id}.")
    return False

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    logger.debug(f"[AdminInterfaceV9_FilterFix] get_time_filter_buttons_v4 with base: {stat_category_base_callback}")
    keyboard = []
    row = []
    # Ensure TIME_FILTERS_DISPLAY uses keys that manager.py expects (e.g., 'all_time')
    for key, text in TIME_FILTERS_DISPLAY.items(): 
        row.append(InlineKeyboardButton(process_arabic_text(text), callback_data=f"{stat_category_base_callback}_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(process_arabic_text("🔙 رجوع للقائمة الرئيسية"), callback_data=f"{STATS_PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

async def stats_admin_panel_command_handler_v4(update: Update, context: CallbackContext):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV9_FilterFix] /adminstats_v4 from user: {user_id}")
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV9_FilterFix] User {user_id} is NOT admin for /adminstats_v4.")
        if update.message:
            await update.message.reply_text(process_arabic_text("عذراً، هذا الأمر مخصص للأدمن فقط."))
        return
    logger.info(f"[AdminInterfaceV9_FilterFix] User {user_id} IS admin. Showing main menu.")
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV9_FilterFix] show_main_stats_menu_v4 for user: {user_id}. Query: {query is not None}")
    keyboard = [
        [InlineKeyboardButton(process_arabic_text("📊 نظرة عامة على الاستخدام"), callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton(process_arabic_text("📈 أداء الاختبارات"), callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton(process_arabic_text("👥 تفاعل المستخدمين"), callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton(process_arabic_text("❓ إحصائيات الأسئلة"), callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = process_arabic_text("لوحة تحكم إحصائيات الأدمن (v9): اختر فئة لعرضها") 
    effective_chat_id = None
    if query and query.message:
        effective_chat_id = query.message.chat_id
    elif update.effective_chat:
        effective_chat_id = update.effective_chat.id

    try:
        if query:
            if query.message: 
                try:
                    await query.edit_message_text(text=message_text, reply_markup=reply_markup)
                except telegram.error.BadRequest as e:
                    if "There is no text in the message to edit" in str(e):
                        logger.warning(f"[AdminInterfaceV9_FilterFix] Cannot edit_message_text for query message (likely a photo). Deleting and sending new. Msg ID: {query.message.message_id}")
                        try:
                            await query.message.delete()
                        except Exception as del_e:
                            logger.error(f"[AdminInterfaceV9_FilterFix] Failed to delete photo message {query.message.message_id}: {del_e}")
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
                    else:
                        logger.error(f"[AdminInterfaceV9_FilterFix] BadRequest editing query message: {e}. Sending new message.", exc_info=True)
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
            else:
                logger.warning("[AdminInterfaceV9_FilterFix] Query object present but query.message is None. Sending new message.")
                if effective_chat_id:
                    await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=message_text, reply_markup=reply_markup)
        elif effective_chat_id: 
             logger.info("[AdminInterfaceV9_FilterFix] No query or message in show_main_stats_menu_v4, sending new message to effective_chat_id.")
             await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        else:
            logger.error("[AdminInterfaceV9_FilterFix] Cannot determine chat_id to send main menu.")

    except Exception as e:
        logger.error(f"[AdminInterfaceV9_FilterFix] General error in show_main_stats_menu_v4: {e}", exc_info=True)
        if effective_chat_id:
            try:
                await context.bot.send_message(chat_id=effective_chat_id, text=process_arabic_text("حدث خطأ أثناء عرض القائمة. يرجى المحاولة باستخدام الأمر /adminstats_v4 مباشرة."), reply_markup=None)
            except Exception as final_e:
                logger.critical(f"[AdminInterfaceV9_FilterFix] CRITICAL: Failed to send any error message in show_main_stats_menu_v4: {final_e}")

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV9_FilterFix] stats_menu_callback from user: {user_id}, data: {query.data}")
    await query.answer() 
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV9_FilterFix] User {user_id} is NOT admin for callback: {query.data}")
        if query.message: 
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message: 
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV9_FilterFix] Error editing auth fail message: {e}")
        return

    callback_data = query.data
    if callback_data == f"{STATS_PREFIX_MAIN_MENU}main":
        await show_main_stats_menu_v4(update, context, query=query)
        return

    stat_category_base = callback_data.replace(STATS_PREFIX_MAIN_MENU, "")
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category_base}"
    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
    stat_category_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_title = process_arabic_text(stat_category_title_map.get(stat_category_base, stat_category_base.replace("_", " ").title()))
    message_text_for_edit = process_arabic_text(f"اختر الفترة الزمنية لـ: {stat_category_title}")
    try:
        if query.message:
            await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV9_FilterFix] Error editing time filter prompt: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV9_FilterFix] stats_fetch_callback from user: {user_id}, data: {query.data}")
    await query.answer()
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV9_FilterFix] User {user_id} is NOT admin for fetch callback: {query.data}")
        if query.message:
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message:
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV9_FilterFix] Error editing auth fail message (fetch): {e}")
        return

    # Corrected parsing logic for callback_data
    # Expected format: STATS_PREFIX_FETCH<category>_<time_filter_key>
    # Example: stats_fetch_v4_usage_overview_today
    # Example: stats_fetch_v4_usage_overview_last_7_days
    # Example: stats_fetch_v4_usage_overview_all_time
    
    raw_data_part = query.data.replace(STATS_PREFIX_FETCH, "") # e.g., usage_overview_today or question_stats_all_time
    
    # Determine the split point for time_filter_key. It's always the last part.
    # Time filter keys can be single words (today, all_time) or multiple words (last_7_days)
    possible_time_filter_keys = list(TIME_FILTERS_DISPLAY.keys()) # ['today', 'last_7_days', 'last_30_days', 'all_time']
    
    stat_category_str = ""
    time_filter_key = ""

    for tf_key in sorted(possible_time_filter_keys, key=len, reverse=True): # Check longer keys first (e.g. last_7_days before today)
        if raw_data_part.endswith(f"_{tf_key}"):
            time_filter_key = tf_key
            stat_category_str = raw_data_part[:-(len(tf_key) + 1)] # +1 for the underscore
            break
    
    if not stat_category_str or not time_filter_key:
        logger.error(f"[AdminInterfaceV9_FilterFix] Could not parse category and time_filter from callback: {query.data}. Raw part: {raw_data_part}")
        if query.message:
            try:
                await query.edit_message_text(text=process_arabic_text("خطأ في تحليل طلب الإحصائيات. يرجى المحاولة مرة أخرى."), reply_markup=None)
            except Exception as e:
                logger.error(f"[AdminInterfaceV9_FilterFix] Error sending parse error message: {e}")
        return

    logger.info(f"[AdminInterfaceV9_FilterFix] Correctly Parsed category: {stat_category_str}, time_filter: {time_filter_key}")
    
    time_filter_text = process_arabic_text(TIME_FILTERS_DISPLAY.get(time_filter_key, time_filter_key)) # Fallback to key if not in display
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_display_title = process_arabic_text(stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title()))
    loading_message_text = process_arabic_text(f"⏳ جاري جلب بيانات {stat_category_display_title} عن فترة: {time_filter_text}...")
    
    original_message_id = query.message.message_id if query.message else None
    try:
        if query.message:
            # Attempt to edit. If it's a photo, this will fail, and we handle it in send_dashboard_stats_v4
            await query.edit_message_text(text=loading_message_text, reply_markup=None) 
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info("[AdminInterfaceV9_FilterFix] Loading message was identical, no edit needed.")
        elif "There is no text in the message to edit" in str(e) and original_message_id:
             logger.info(f"[AdminInterfaceV9_FilterFix] Cannot edit loading message for message {original_message_id} (likely photo). Will delete and resend in send_dashboard_stats_v4.")
        else:
            logger.error(f"[AdminInterfaceV9_FilterFix] Error editing loading message: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[AdminInterfaceV9_FilterFix] General error editing loading message: {e}", exc_info=True)

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key, stat_category_display_title, original_message_id)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str, stat_category_display_title: str, original_message_id_to_delete: int | None):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV9_FilterFix] send_dashboard_stats for {stat_category}, filter {time_filter}, user {user_id}")
    
    text_response = ""
    chart_paths = []
    chat_id = query.message.chat_id if query.message else None
    current_reply_markup = None 

    if not chat_id:
        logger.error("[AdminInterfaceV9_FilterFix] Cannot determine chat_id in send_dashboard_stats_v4.")
        return

    try:
        fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
        current_reply_markup = get_time_filter_buttons_v4(fetch_base_callback)

        # Ensure the time_filter key passed to display functions is what manager.py expects
        # TIME_FILTERS_DISPLAY keys should align with manager.py's _get_time_filter_condition keys

        if stat_category == "usage_overview":
            text_response, chart_path_single = await get_usage_overview_display(time_filter)
            if chart_path_single: chart_paths.append(chart_path_single)
        elif stat_category == "quiz_performance":
            text_response, chart_path_single = await get_quiz_performance_display(time_filter)
            if chart_path_single: chart_paths.append(chart_path_single)
        elif stat_category == "user_interaction":
            text_response, chart_path_single = await get_user_interaction_display(time_filter)
            if chart_path_single: chart_paths.append(chart_path_single)
        elif stat_category == "question_stats":
            text_response, chart_paths_list = await get_question_stats_display(time_filter)
            if chart_paths_list: chart_paths.extend(chart_paths_list)
        else:
            logger.warning(f"[AdminInterfaceV9_FilterFix] Unknown stat_category: {stat_category}")
            text_response = process_arabic_text(f"فئة الإحصائيات \"{stat_category_display_title}\" غير معروفة.")

        if not text_response and not (chart_paths and any(os.path.exists(p) for p in chart_paths if p)):
             text_response = process_arabic_text(f"لا توجد بيانات لعرضها حالياً لـ {stat_category_display_title} عن فترة {TIME_FILTERS_DISPLAY.get(time_filter, time_filter)}.")

        processed_text_response = process_arabic_text(text_response) 

        # Delete the "Loading..." message or the previous photo message
        if original_message_id_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id_to_delete)
                logger.info(f"[AdminInterfaceV9_FilterFix] Deleted original message {original_message_id_to_delete} before sending new stats.")
            except Exception as del_err:
                logger.warning(f"[AdminInterfaceV9_FilterFix] Could not delete original message {original_message_id_to_delete}: {del_err}")

        valid_chart_paths = [p for p in chart_paths if p and os.path.exists(p)]

        if valid_chart_paths:
            logger.info(f"Charts found for {stat_category}. Sending photo(s).")
            media_group = []
            caption_text = process_arabic_text(f"{processed_text_response}\n\n🖼️ {stat_category_display_title} ({TIME_FILTERS_DISPLAY.get(time_filter, time_filter)})")

            if len(valid_chart_paths) == 1:
                with open(valid_chart_paths[0], "rb") as photo_file:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption_text, reply_markup=current_reply_markup)
            else:
                for i, chart_p in enumerate(valid_chart_paths):
                    media_group.append(InputMediaPhoto(media=open(chart_p, "rb"), caption=caption_text if i == 0 else None))
                if media_group:
                    sent_messages = await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                    # PTB does not easily allow adding reply_markup to send_media_group directly.
                    # Send a follow-up message with the text and buttons if it's a media group.
                    # Or, if the text_response is short enough, it's part of the caption of the first image.
                    # For now, the caption on the first image contains the text. We might need a separate message for buttons if media group is used.
                    # Let's try sending a new message with buttons if it's a media group and text is substantial.
                    if len(valid_chart_paths) > 1: # If it was a media group
                         await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("اختر فلتر آخر أو عد للقائمة الرئيسية:"), reply_markup=current_reply_markup)
        else:
            logger.info(f"No charts for {stat_category}, sending text only.")
            await context.bot.send_message(chat_id=chat_id, text=processed_text_response, reply_markup=current_reply_markup)

    except telegram.error.BadRequest as e:
        if "message to be replied not found" in str(e).lower() or "reply message not found" in str(e).lower():
            logger.warning(f"[AdminInterfaceV9_FilterFix] Original message for reply not found. Sending new message. Error: {e}")
            await context.bot.send_message(chat_id=chat_id, text=processed_text_response, reply_markup=current_reply_markup)
        else:
            logger.error(f"[AdminInterfaceV9_FilterFix] Telegram BadRequest in send_dashboard_stats_v4: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("حدث خطأ أثناء عرض الإحصائيات. يرجى المحاولة مرة أخرى."), reply_markup=get_time_filter_buttons_v4(f"{STATS_PREFIX_FETCH}{stat_category}")) # Offer retry with filters
    except Exception as e:
        logger.error(f"[AdminInterfaceV9_FilterFix] General error in send_dashboard_stats_v4: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("عفواً، حدث خطأ غير متوقع أثناء جلب الإحصائيات."), reply_markup=get_time_filter_buttons_v4(f"{STATS_PREFIX_FETCH}{stat_category}"))
        except Exception as final_err:
            logger.critical(f"[AdminInterfaceV9_FilterFix] CRITICAL: Failed to send error message in send_dashboard_stats_v4: {final_err}")
    finally:
        # Clean up chart files
        for chart_p in chart_paths:
            if chart_p and os.path.exists(chart_p):
                try:
                    os.remove(chart_p)
                    logger.info(f"[AdminInterfaceV9_FilterFix] Cleaned up chart file: {chart_p}")
                except Exception as e_clean:
                    logger.error(f"[AdminInterfaceV9_FilterFix] Error cleaning up chart file {chart_p}: {e_clean}")


# Define handlers
stats_admin_panel_command_handler_v9 = CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)
stats_menu_callback_handler_v9 = CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")
stats_fetch_callback_handler_v9 = CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")

logger.info("[AdminInterfaceV9_FilterFix] All function definitions complete.")

