"""
admin_interface.py (v12 - Arabic Fix: Relies on corrected process_arabic_text from admin_dashboard_display)

Handles the admin statistics dashboard interface. This version removes the diagnostic
message from v11, assuming the Arabic text processing issue is resolved in the
imported process_arabic_text function from the admin_dashboard_display module.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import telegram.error # Import for specific error handling
import os

from utils.admin_auth import is_admin as is_admin_original # Renamed to avoid conflict
from database.manager import DB_MANAGER
from config import logger

# This import will now pull the corrected process_arabic_text from the updated admin_dashboard_display module
from .admin_dashboard_display import (
    get_usage_overview_display,
    get_quiz_performance_display,
    get_user_interaction_display,
    get_question_stats_display,
    TIME_FILTERS_DISPLAY_RAW, 
    get_processed_time_filter_display, 
    process_arabic_text 
)

STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"

logger.info("[AdminInterfaceV12_ArabicFix] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV12_ArabicFix] is_admin: No effective_user found.")
        return False
    user_id = user.id
    if hasattr(DB_MANAGER, 'is_user_admin'):
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV12_ArabicFix] is_admin: DB_MANAGER error for {user_id}: {e}", exc_info=True)
            return False
    logger.warning(f"[AdminInterfaceV12_ArabicFix] is_admin: DB_MANAGER.is_user_admin not found. Defaulting to False for {user_id}.")
    return False

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    keyboard = []
    row = []
    for key, raw_text in TIME_FILTERS_DISPLAY_RAW.items():
        # Uses the (now corrected) imported process_arabic_text
        row.append(InlineKeyboardButton(process_arabic_text(raw_text), callback_data=f"{stat_category_base_callback}_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(process_arabic_text("🔙 رجوع للقائمة الرئيسية"), callback_data=f"{STATS_PREFIX_MAIN_MENU}main")])
    return InlineKeyboardMarkup(keyboard)

async def stats_admin_panel_command_handler_v4(update: Update, context: CallbackContext):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV12_ArabicFix] /adminstats_v4 from user: {user_id}")
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV12_ArabicFix] User {user_id} is NOT admin for /adminstats_v4.")
        if update.message:
            await update.message.reply_text(process_arabic_text("عذراً، هذا الأمر مخصص للأدمن فقط."))
        return
    logger.info(f"[AdminInterfaceV12_ArabicFix] User {user_id} IS admin.")

    # Diagnostic message from v11 has been removed.
    logger.info(f"[AdminInterfaceV12_ArabicFix] Showing main menu for user {user_id}.")
    await show_main_stats_menu_v4(update, context) 

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    keyboard = [
        [InlineKeyboardButton(process_arabic_text("📊 نظرة عامة على الاستخدام"), callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton(process_arabic_text("📈 أداء الاختبارات"), callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton(process_arabic_text("👥 تفاعل المستخدمين"), callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton(process_arabic_text("❓ إحصائيات الأسئلة"), callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = process_arabic_text("لوحة تحكم إحصائيات الأدمن (v12): اختر فئة لعرضها") 
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
                        logger.warning(f"[AdminInterfaceV12_ArabicFix] Cannot edit_message_text (photo?). Deleting and sending new. Msg ID: {query.message.message_id}")
                        try:
                            await query.message.delete()
                        except Exception as del_e:
                            logger.error(f"[AdminInterfaceV12_ArabicFix] Failed to delete photo message {query.message.message_id}: {del_e}")
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
                    else:
                        logger.error(f"[AdminInterfaceV12_ArabicFix] BadRequest editing query message: {e}. Sending new.", exc_info=True)
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
            else:
                logger.warning("[AdminInterfaceV12_ArabicFix] Query object but query.message is None. Sending new.")
                if effective_chat_id:
                    await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        elif update.message:
            if not query: 
                await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        elif effective_chat_id: 
             logger.info("[AdminInterfaceV12_ArabicFix] No query/message, sending new to effective_chat_id.")
             await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        else:
            logger.error("[AdminInterfaceV12_ArabicFix] Cannot determine chat_id for main menu.")

    except Exception as e:
        logger.error(f"[AdminInterfaceV12_ArabicFix] General error in show_main_stats_menu_v4: {e}", exc_info=True)
        if effective_chat_id:
            try:
                await context.bot.send_message(chat_id=effective_chat_id, text=process_arabic_text("حدث خطأ أثناء عرض القائمة. يرجى المحاولة بـ /adminstats_v4."), reply_markup=None)
            except Exception as final_e:
                logger.critical(f"[AdminInterfaceV12_ArabicFix] CRITICAL: Failed to send error message in show_main_stats_menu_v4: {final_e}")

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    await query.answer() 
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV12_ArabicFix] User {user_id} NOT admin for callback: {query.data}")
        if query.message: 
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message: 
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV12_ArabicFix] Error editing auth fail message: {e}")
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
    raw_stat_category_title = stat_category_title_map.get(stat_category_base, stat_category_base.replace("_", " ").title())
    processed_stat_category_title = process_arabic_text(raw_stat_category_title)
    message_text_for_edit = f"{process_arabic_text('اختر الفترة الزمنية لـ:')} {processed_stat_category_title}"
    try:
        if query.message:
            await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV12_ArabicFix] Error editing time filter prompt: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV12_ArabicFix] stats_fetch_callback from user: {user_id}, data: {query.data}")
    await query.answer()
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV12_ArabicFix] User {user_id} NOT admin for fetch: {query.data}")
        return

    raw_data_part = query.data.replace(STATS_PREFIX_FETCH, "")
    possible_time_filter_keys = list(TIME_FILTERS_DISPLAY_RAW.keys())
    stat_category_str = ""
    time_filter_key = ""

    for tf_key in sorted(possible_time_filter_keys, key=len, reverse=True):
        if raw_data_part.endswith(f"_{tf_key}"):
            time_filter_key = tf_key
            stat_category_str = raw_data_part[:-(len(tf_key) + 1)]
            break
    
    if not stat_category_str or not time_filter_key:
        logger.error(f"[AdminInterfaceV12_ArabicFix] Could not parse category/filter from: {query.data}")
        if query.message:
            try: 
                await query.edit_message_text(text=process_arabic_text("خطأ في تحليل طلب الإحصائيات. حاول مرة أخرى."), reply_markup=None)
            except Exception as e:
                logger.error(f"[AdminInterfaceV12_ArabicFix] Error sending parse error: {e}")
        return

    logger.info(f"[AdminInterfaceV12_ArabicFix] Parsed category: {stat_category_str}, time_filter: {time_filter_key}")
    time_filter_text_processed = get_processed_time_filter_display(time_filter_key)
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    raw_stat_category_display_title = stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title())
    processed_stat_category_display_title = process_arabic_text(raw_stat_category_display_title)
    loading_message_text = f"{process_arabic_text('⏳ جاري جلب بيانات')} {processed_stat_category_display_title} {process_arabic_text('عن فترة:')} {time_filter_text_processed}..."
    original_message_id = query.message.message_id if query.message else None
    try:
        if query.message:
            await query.edit_message_text(text=loading_message_text, reply_markup=None) 
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info("[AdminInterfaceV12_ArabicFix] Loading message identical, no edit.")
        elif "There is no text in the message to edit" in str(e) and original_message_id:
             logger.info(f"[AdminInterfaceV12_ArabicFix] Cannot edit loading message (photo?) for {original_message_id}.")
        else:
            logger.error(f"[AdminInterfaceV12_ArabicFix] Error editing loading message: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[AdminInterfaceV12_ArabicFix] General error editing loading message: {e}", exc_info=True)

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key, processed_stat_category_display_title, original_message_id)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str, processed_stat_category_display_title: str, original_message_id_to_delete: int | None):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    text_response = ""
    chart_paths = []
    chat_id = query.message.chat_id if query.message else None
    current_reply_markup = None 

    if not chat_id:
        logger.error("[AdminInterfaceV12_ArabicFix] Cannot determine chat_id in send_dashboard_stats_v4.")
        return

    try:
        fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
        current_reply_markup = get_time_filter_buttons_v4(fetch_base_callback)

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
            logger.warning(f"[AdminInterfaceV12_ArabicFix] Unknown stat_category: {stat_category}")
            text_response = f"{process_arabic_text('فئة الإحصائيات غير معروفة:')} {processed_stat_category_display_title}"

        if not text_response and not (chart_paths and any(os.path.exists(p) for p in chart_paths if p)):
             time_filter_display_for_message = get_processed_time_filter_display(time_filter)
             text_response = f"{process_arabic_text('لا توجد بيانات لعرضها حالياً لـ')} {processed_stat_category_display_title} {process_arabic_text('عن فترة')} {time_filter_display_for_message}."

        if original_message_id_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id_to_delete)
            except Exception as del_err:
                logger.warning(f"[AdminInterfaceV12_ArabicFix] Could not delete original message {original_message_id_to_delete}: {del_err}")

        MAX_CAPTION_LENGTH = 1000  # Max length for a photo caption
        MAX_MESSAGE_LENGTH = 4000 # Max length for a text message (approx)

        valid_chart_paths = [p for p in chart_paths if p and os.path.exists(p)]
        
        final_caption_for_photo = None
        send_text_separately = False
        
        if text_response:
            if len(text_response) > MAX_CAPTION_LENGTH:
                final_caption_for_photo = process_arabic_text("الرسم البياني. التفاصيل في الرسالة التالية.")
                send_text_separately = True
            else:
                final_caption_for_photo = text_response
        
        if valid_chart_paths:
            if len(valid_chart_paths) == 1:
                await context.bot.send_photo(
                    chat_id=chat_id, 
                    photo=open(valid_chart_paths[0], "rb"), 
                    caption=final_caption_for_photo
                )
            else: # Multiple photos
                media_group_items = []
                # First photo with caption
                media_group_items.append(InputMediaPhoto(media=open(valid_chart_paths[0], "rb"), caption=final_caption_for_photo))
                # Remaining photos without caption
                for chart_path in valid_chart_paths[1:]:
                    media_group_items.append(InputMediaPhoto(media=open(chart_path, "rb")))
                await context.bot.send_media_group(chat_id=chat_id, media=media_group_items)

            if send_text_separately and text_response:
                for i in range(0, len(text_response), MAX_MESSAGE_LENGTH):
                    chunk = text_response[i:i + MAX_MESSAGE_LENGTH]
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
            
            # Send reply markup if charts were sent
            if current_reply_markup:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=process_arabic_text("اختر فلترًا آخر أو عد للقائمة الرئيسية."), 
                    reply_markup=current_reply_markup
                )
            
            for p in valid_chart_paths:
                try:
                    os.remove(p)
                except Exception as e_remove:
                    logger.error(f"[AdminInterfaceV14_CaptionFix] Error removing chart file {p}: {e_remove}")
        
        elif text_response: # No charts, only text response
            for i in range(0, len(text_response), MAX_MESSAGE_LENGTH):
                chunk = text_response[i:i + MAX_MESSAGE_LENGTH]
                # Send the last chunk with reply_markup
                if i + MAX_MESSAGE_LENGTH >= len(text_response):
                    await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=current_reply_markup)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
        
        else: # No charts, no text (should be caught by \"no data\" message)
            if current_reply_markup: # Send markup if it exists
                await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("لا توجد بيانات أو رسوم بيانية لعرضها."), reply_markup=current_reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("لا توجد بيانات أو رسوم بيانية لعرضها."))
    except Exception as e:
        logger.error(f"[AdminInterfaceV12_ArabicFix] Error in send_dashboard_stats_v4 for {stat_category} ({time_filter}): {e}", exc_info=True)
        error_message = process_arabic_text("حدث خطأ أثناء جلب أو عرض الإحصائيات. يرجى المحاولة مرة أخرى أو الاتصال بالدعم.")
        try:
            if original_message_id_to_delete and chat_id:
                 try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id_to_delete)
                 except Exception: pass # Ignore if deletion fails, main thing is to send error
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text=error_message, reply_markup=get_time_filter_buttons_v4(f"{STATS_PREFIX_FETCH}{stat_category}") if stat_category else None)
        except Exception as final_err:
            logger.critical(f"[AdminInterfaceV12_ArabicFix] CRITICAL: Failed to send error message in send_dashboard_stats_v4: {final_err}")

# Handlers
STATS_COMMAND_HANDLER_V4 = CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)
STATS_MENU_CALLBACK_HANDLER_V4 = CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")
STATS_FETCH_CALLBACK_HANDLER_V4 = CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")

logger.info("[AdminInterfaceV12_ArabicFix] Admin interface handlers (v4) prepared.")

