"""
admin_interface.py (v10 - Arabic Text Refactor for single processing)

Handles the admin statistics dashboard interface. This version ensures that Arabic text
processing (reshaping, bidi) is handled consistently and ideally only once,
relying on admin_dashboard_display to process texts it generates, and this module
processing texts it displays directly.

It imports TIME_FILTERS_DISPLAY_RAW and get_processed_time_filter_display from
admin_dashboard_display_v14.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import telegram.error # Import for specific error handling
import os

from utils.admin_auth import is_admin as is_admin_original # Renamed to avoid conflict
from database.manager import DB_MANAGER
from config import logger

# Import functions and RAW text from admin_dashboard_display
# admin_dashboard_display is now responsible for processing its own texts before returning.
# process_arabic_text is still used here for texts generated and displayed solely by admin_interface.
from .admin_dashboard_display import (
    get_usage_overview_display,
    get_quiz_performance_display,
    get_user_interaction_display,
    get_question_stats_display,
    TIME_FILTERS_DISPLAY_RAW,  # Raw Arabic strings for time filters
    get_processed_time_filter_display, # Function to get processed display string for a filter key
    process_arabic_text # For texts local to this module
)

STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"

logger.info("[AdminInterfaceV10_ArabicRefactor] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV10_ArabicRefactor] is_admin: No effective_user found.")
        return False
    user_id = user.id
    # logger.info(f"[AdminInterfaceV10_ArabicRefactor] is_admin: Checking admin for user_id: {user_id}")
    if hasattr(DB_MANAGER, 'is_user_admin'):
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            # logger.info(f"[AdminInterfaceV10_ArabicRefactor] is_admin: DB_MANAGER returned {admin_status} for {user_id}")
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV10_ArabicRefactor] is_admin: DB_MANAGER error for {user_id}: {e}", exc_info=True)
            return False
    logger.warning(f"[AdminInterfaceV10_ArabicRefactor] is_admin: DB_MANAGER.is_user_admin not found. Defaulting to False for {user_id}.")
    return False

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    # logger.debug(f"[AdminInterfaceV10_ArabicRefactor] get_time_filter_buttons_v4 with base: {stat_category_base_callback}")
    keyboard = []
    row = []
    # Iterate over RAW Arabic strings from TIME_FILTERS_DISPLAY_RAW
    # Process them here because these button labels are displayed directly by admin_interface
    for key, raw_text in TIME_FILTERS_DISPLAY_RAW.items():
        row.append(InlineKeyboardButton(process_arabic_text(raw_text), callback_data=f"{stat_category_base_callback}_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    # Process the "Back" button text here
    keyboard.append([InlineKeyboardButton(process_arabic_text("🔙 رجوع للقائمة الرئيسية"), callback_data=f"{STATS_PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

async def stats_admin_panel_command_handler_v4(update: Update, context: CallbackContext):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV10_ArabicRefactor] /adminstats_v4 from user: {user_id}")
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV10_ArabicRefactor] User {user_id} is NOT admin for /adminstats_v4.")
        if update.message:
            await update.message.reply_text(process_arabic_text("عذراً، هذا الأمر مخصص للأدمن فقط."))
        return
    logger.info(f"[AdminInterfaceV10_ArabicRefactor] User {user_id} IS admin. Showing main menu.")
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    # logger.info(f"[AdminInterfaceV10_ArabicRefactor] show_main_stats_menu_v4 for user: {user_id}. Query: {query is not None}")
    # Process button texts here as they are displayed by admin_interface
    keyboard = [
        [InlineKeyboardButton(process_arabic_text("📊 نظرة عامة على الاستخدام"), callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton(process_arabic_text("📈 أداء الاختبارات"), callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton(process_arabic_text("👥 تفاعل المستخدمين"), callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton(process_arabic_text("❓ إحصائيات الأسئلة"), callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Process message text here
    message_text = process_arabic_text("لوحة تحكم إحصائيات الأدمن (v10): اختر فئة لعرضها") 
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
                        logger.warning(f"[AdminInterfaceV10_ArabicRefactor] Cannot edit_message_text (photo?). Deleting and sending new. Msg ID: {query.message.message_id}")
                        try:
                            await query.message.delete()
                        except Exception as del_e:
                            logger.error(f"[AdminInterfaceV10_ArabicRefactor] Failed to delete photo message {query.message.message_id}: {del_e}")
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
                    else:
                        logger.error(f"[AdminInterfaceV10_ArabicRefactor] BadRequest editing query message: {e}. Sending new.", exc_info=True)
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
            else:
                logger.warning("[AdminInterfaceV10_ArabicRefactor] Query object but query.message is None. Sending new.")
                if effective_chat_id:
                    await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=message_text, reply_markup=reply_markup)
        elif effective_chat_id: 
             logger.info("[AdminInterfaceV10_ArabicRefactor] No query/message, sending new to effective_chat_id.")
             await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        else:
            logger.error("[AdminInterfaceV10_ArabicRefactor] Cannot determine chat_id for main menu.")

    except Exception as e:
        logger.error(f"[AdminInterfaceV10_ArabicRefactor] General error in show_main_stats_menu_v4: {e}", exc_info=True)
        if effective_chat_id:
            try:
                await context.bot.send_message(chat_id=effective_chat_id, text=process_arabic_text("حدث خطأ أثناء عرض القائمة. يرجى المحاولة بـ /adminstats_v4."), reply_markup=None)
            except Exception as final_e:
                logger.critical(f"[AdminInterfaceV10_ArabicRefactor] CRITICAL: Failed to send error message in show_main_stats_menu_v4: {final_e}")

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    # logger.info(f"[AdminInterfaceV10_ArabicRefactor] stats_menu_callback from user: {user_id}, data: {query.data}")
    await query.answer() 
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV10_ArabicRefactor] User {user_id} NOT admin for callback: {query.data}")
        if query.message: 
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message: 
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV10_ArabicRefactor] Error editing auth fail message: {e}")
        return

    callback_data = query.data
    if callback_data == f"{STATS_PREFIX_MAIN_MENU}main":
        await show_main_stats_menu_v4(update, context, query=query)
        return

    stat_category_base = callback_data.replace(STATS_PREFIX_MAIN_MENU, "")
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category_base}"
    reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
    
    # Raw titles, will be processed before display
    stat_category_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    raw_stat_category_title = stat_category_title_map.get(stat_category_base, stat_category_base.replace("_", " ").title())
    # Process the title here as it's for admin_interface display
    processed_stat_category_title = process_arabic_text(raw_stat_category_title)
    
    # Construct the message, processing the static part. processed_stat_category_title is already done.
    message_text_for_edit = f"{process_arabic_text('اختر الفترة الزمنية لـ:')} {processed_stat_category_title}"
    try:
        if query.message:
            await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV10_ArabicRefactor] Error editing time filter prompt: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV10_ArabicRefactor] stats_fetch_callback from user: {user_id}, data: {query.data}")
    await query.answer()
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV10_ArabicRefactor] User {user_id} NOT admin for fetch: {query.data}")
        # Process error message text here
        # ... (similar to above error handling)
        return

    raw_data_part = query.data.replace(STATS_PREFIX_FETCH, "")
    possible_time_filter_keys = list(TIME_FILTERS_DISPLAY_RAW.keys()) # Use RAW keys
    stat_category_str = ""
    time_filter_key = ""

    for tf_key in sorted(possible_time_filter_keys, key=len, reverse=True):
        if raw_data_part.endswith(f"_{tf_key}"):
            time_filter_key = tf_key
            stat_category_str = raw_data_part[:-(len(tf_key) + 1)]
            break
    
    if not stat_category_str or not time_filter_key:
        logger.error(f"[AdminInterfaceV10_ArabicRefactor] Could not parse category/filter from: {query.data}")
        if query.message:
            try: # Process error message text here
                await query.edit_message_text(text=process_arabic_text("خطأ في تحليل طلب الإحصائيات. حاول مرة أخرى."), reply_markup=None)
            except Exception as e:
                logger.error(f"[AdminInterfaceV10_ArabicRefactor] Error sending parse error: {e}")
        return

    logger.info(f"[AdminInterfaceV10_ArabicRefactor] Parsed category: {stat_category_str}, time_filter: {time_filter_key}")
    
    # Get processed display text for the time filter (this calls process_arabic_text internally)
    time_filter_text_processed = get_processed_time_filter_display(time_filter_key)
    
    # Raw titles for display categories
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    raw_stat_category_display_title = stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title())
    # Process the title here for the loading message
    processed_stat_category_display_title = process_arabic_text(raw_stat_category_display_title)

    # Construct loading message. processed_stat_category_display_title and time_filter_text_processed are already processed.
    # Static parts of the message need processing.
    loading_message_text = f"{process_arabic_text('⏳ جاري جلب بيانات')} {processed_stat_category_display_title} {process_arabic_text('عن فترة:')} {time_filter_text_processed}..."
    
    original_message_id = query.message.message_id if query.message else None
    try:
        if query.message:
            await query.edit_message_text(text=loading_message_text, reply_markup=None) 
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info("[AdminInterfaceV10_ArabicRefactor] Loading message identical, no edit.")
        elif "There is no text in the message to edit" in str(e) and original_message_id:
             logger.info(f"[AdminInterfaceV10_ArabicRefactor] Cannot edit loading message (photo?) for {original_message_id}.")
        else:
            logger.error(f"[AdminInterfaceV10_ArabicRefactor] Error editing loading message: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[AdminInterfaceV10_ArabicRefactor] General error editing loading message: {e}", exc_info=True)

    # Pass the ALREADY PROCESSED stat_category_display_title
    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key, processed_stat_category_display_title, original_message_id)

# Note: processed_stat_category_display_title is ALREADY PROCESSED when passed here
async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str, processed_stat_category_display_title: str, original_message_id_to_delete: int | None):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    # logger.info(f"[AdminInterfaceV10_ArabicRefactor] send_dashboard_stats for {stat_category}, filter {time_filter}, user {user_id}")
    
    # text_response from dashboard_display functions is assumed to be ALREADY PROCESSED by those functions.
    text_response = ""
    chart_paths = []
    chat_id = query.message.chat_id if query.message else None
    current_reply_markup = None 

    if not chat_id:
        logger.error("[AdminInterfaceV10_ArabicRefactor] Cannot determine chat_id in send_dashboard_stats_v4.")
        return

    try:
        fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
        current_reply_markup = get_time_filter_buttons_v4(fetch_base_callback) # Buttons text processed in getter

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
            logger.warning(f"[AdminInterfaceV10_ArabicRefactor] Unknown stat_category: {stat_category}")
            # processed_stat_category_display_title is already processed. Process static part.
            text_response = f"{process_arabic_text('فئة الإحصائيات غير معروفة:')} {processed_stat_category_display_title}"

        # If text_response is empty and no charts, create a processed fallback message.
        if not text_response and not (chart_paths and any(os.path.exists(p) for p in chart_paths if p)):
             time_filter_display_for_message = get_processed_time_filter_display(time_filter) # This is processed
             # processed_stat_category_display_title is already processed.
             text_response = f"{process_arabic_text('لا توجد بيانات لعرضها حالياً لـ')} {processed_stat_category_display_title} {process_arabic_text('عن فترة')} {time_filter_display_for_message}."

        # text_response is now guaranteed to be processed (either from dashboard_display or from fallbacks above)

        if original_message_id_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id_to_delete)
                # logger.info(f"[AdminInterfaceV10_ArabicRefactor] Deleted original message {original_message_id_to_delete}.")
            except Exception as del_err:
                logger.warning(f"[AdminInterfaceV10_ArabicRefactor] Could not delete original message {original_message_id_to_delete}: {del_err}")

        valid_chart_paths = [p for p in chart_paths if p and os.path.exists(p)]

        if valid_chart_paths:
            # logger.info(f"Charts found for {stat_category}. Sending photo(s).")
            # Construct caption. All components are already processed.
            caption_text = f"{text_response}\n\n{process_arabic_text('🖼️')} {processed_stat_category_display_title} ({get_processed_time_filter_display(time_filter)})"

            if len(valid_chart_paths) == 1:
                with open(valid_chart_paths[0], "rb") as photo_file:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption_text, reply_markup=current_reply_markup)
            else:
                media_group = []
                for i, chart_p in enumerate(valid_chart_paths):
                    media_group.append(InputMediaPhoto(media=open(chart_p, "rb"), caption=caption_text if i == 0 else None))
                if media_group:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                    if len(valid_chart_paths) > 1:
                         await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("اختر فلتر آخر أو عد للقائمة الرئيسية:"), reply_markup=current_reply_markup)
        else:
            # logger.info(f"No charts for {stat_category}, sending text only.")
            # text_response is already processed.
            await context.bot.send_message(chat_id=chat_id, text=text_response, reply_markup=current_reply_markup)

    except telegram.error.BadRequest as e:
        if "message to be replied not found" in str(e).lower() or "reply message not found" in str(e).lower():
            logger.warning(f"[AdminInterfaceV10_ArabicRefactor] Original message for reply not found. Sending new. Error: {e}")
            # text_response is already processed if it was generated, otherwise process the error message.
            final_text_to_send = text_response if text_response else process_arabic_text("حدث خطأ أثناء عرض الإحصائيات. حاول مرة أخرى.")
            await context.bot.send_message(chat_id=chat_id, text=final_text_to_send, reply_markup=current_reply_markup)
        else:
            logger.error(f"[AdminInterfaceV10_ArabicRefactor] Telegram BadRequest in send_dashboard_stats_v4: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("حدث خطأ أثناء عرض الإحصائيات. يرجى المحاولة مرة أخرى."), reply_markup=get_time_filter_buttons_v4(f"{STATS_PREFIX_FETCH}{stat_category}"))
    except Exception as e:
        logger.error(f"[AdminInterfaceV10_ArabicRefactor] General error in send_dashboard_stats_v4: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("عفواً، حدث خطأ غير متوقع أثناء جلب الإحصائيات."), reply_markup=get_time_filter_buttons_v4(f"{STATS_PREFIX_FETCH}{stat_category}"))
        except Exception as final_err:
            logger.critical(f"[AdminInterfaceV10_ArabicRefactor] CRITICAL: Failed to send error message: {final_err}")
    finally:
        for chart_p in chart_paths:
            if chart_p and os.path.exists(chart_p):
                try:
                    os.remove(chart_p)
                    # logger.info(f"[AdminInterfaceV10_ArabicRefactor] Cleaned up chart file: {chart_p}")
                except Exception as e_clean:
                    logger.error(f"[AdminInterfaceV10_ArabicRefactor] Error cleaning up chart file {chart_p}: {e_clean}")

stats_admin_panel_command_handler_v10 = CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)
stats_menu_callback_handler_v10 = CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")
stats_fetch_callback_handler_v10 = CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")

logger.info("[AdminInterfaceV10_ArabicRefactor] All function definitions complete.")

