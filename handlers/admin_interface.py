"""
admin_interface.py (v8 - Arabic Fix and consistent with v7 error handling)

Handles the admin statistics dashboard interface, including command handling,
callback queries for menu navigation, and fetching/displaying statistics.

This version is functionally identical to v7 but renamed for clarity in the debugging process.
Ensures all user-facing Arabic strings are passed through process_arabic_text.
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
    TIME_FILTERS_DISPLAY,
    process_arabic_text
)

STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"

logger.info("[AdminInterfaceV8_ArabicFix] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV8_ArabicFix] is_admin: No effective_user found.")
        return False
    user_id = user.id
    logger.info(f"[AdminInterfaceV8_ArabicFix] is_admin: Checking admin for user_id: {user_id}")
    if hasattr(DB_MANAGER, 'is_user_admin'):
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            logger.info(f"[AdminInterfaceV8_ArabicFix] is_admin: DB_MANAGER returned {admin_status} for {user_id}")
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV8_ArabicFix] is_admin: DB_MANAGER error for {user_id}: {e}", exc_info=True)
            return False
    logger.warning(f"[AdminInterfaceV8_ArabicFix] is_admin: DB_MANAGER.is_user_admin not found. Defaulting to False for {user_id}.")
    return False

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    logger.debug(f"[AdminInterfaceV8_ArabicFix] get_time_filter_buttons_v4 with base: {stat_category_base_callback}")
    keyboard = []
    row = []
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
    logger.info(f"[AdminInterfaceV8_ArabicFix] /adminstats_v4 from user: {user_id}")
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV8_ArabicFix] User {user_id} is NOT admin for /adminstats_v4.")
        if update.message:
            await update.message.reply_text(process_arabic_text("عذراً، هذا الأمر مخصص للأدمن فقط."))
        return
    logger.info(f"[AdminInterfaceV8_ArabicFix] User {user_id} IS admin. Showing main menu.")
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV8_ArabicFix] show_main_stats_menu_v4 for user: {user_id}. Query: {query is not None}")
    keyboard = [
        [InlineKeyboardButton(process_arabic_text("📊 نظرة عامة على الاستخدام"), callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton(process_arabic_text("📈 أداء الاختبارات"), callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton(process_arabic_text("👥 تفاعل المستخدمين"), callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton(process_arabic_text("❓ إحصائيات الأسئلة"), callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = process_arabic_text("لوحة تحكم إحصائيات الأدمن (v8): اختر فئة لعرضها") # Updated version in text
    effective_chat_id = None
    if query and query.message:
        effective_chat_id = query.message.chat_id
    elif update.effective_chat:
        effective_chat_id = update.effective_chat.id

    try:
        if query:
            if query.message: # Ensure query.message exists
                try:
                    await query.edit_message_text(text=message_text, reply_markup=reply_markup)
                except telegram.error.BadRequest as e:
                    if "There is no text in the message to edit" in str(e):
                        logger.warning(f"[AdminInterfaceV8_ArabicFix] Cannot edit_message_text for query message (likely a photo). Deleting and sending new. Msg ID: {query.message.message_id}")
                        try:
                            await query.message.delete()
                        except Exception as del_e:
                            logger.error(f"[AdminInterfaceV8_ArabicFix] Failed to delete photo message {query.message.message_id}: {del_e}")
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
                    else:
                        logger.error(f"[AdminInterfaceV8_ArabicFix] BadRequest editing query message: {e}. Sending new message.", exc_info=True)
                        if effective_chat_id:
                            await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
            else:
                logger.warning("[AdminInterfaceV8_ArabicFix] Query object present but query.message is None. Sending new message.")
                if effective_chat_id:
                    await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=message_text, reply_markup=reply_markup)
        elif effective_chat_id: # Fallback if no query and no direct message, but chat_id is known
             logger.info("[AdminInterfaceV8_ArabicFix] No query or message in show_main_stats_menu_v4, sending new message to effective_chat_id.")
             await context.bot.send_message(chat_id=effective_chat_id, text=message_text, reply_markup=reply_markup)
        else:
            logger.error("[AdminInterfaceV8_ArabicFix] Cannot determine chat_id to send main menu.")

    except Exception as e:
        logger.error(f"[AdminInterfaceV8_ArabicFix] General error in show_main_stats_menu_v4: {e}", exc_info=True)
        if effective_chat_id:
            try:
                await context.bot.send_message(chat_id=effective_chat_id, text=process_arabic_text("حدث خطأ أثناء عرض القائمة. يرجى المحاولة باستخدام الأمر /adminstats_v4 مباشرة."), reply_markup=None)
            except Exception as final_e:
                logger.critical(f"[AdminInterfaceV8_ArabicFix] CRITICAL: Failed to send any error message in show_main_stats_menu_v4: {final_e}")

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV8_ArabicFix] stats_menu_callback from user: {user_id}, data: {query.data}")
    await query.answer() # Answer callback quickly
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV8_ArabicFix] User {user_id} is NOT admin for callback: {query.data}")
        if query.message: # Try to edit the message the button was on
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message: # If it was a photo message
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV8_ArabicFix] Error editing auth fail message: {e}")
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
        logger.error(f"[AdminInterfaceV8_ArabicFix] Error editing time filter prompt: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV8_ArabicFix] stats_fetch_callback from user: {user_id}, data: {query.data}")
    await query.answer() # Answer callback quickly
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV8_ArabicFix] User {user_id} is NOT admin for fetch callback: {query.data}")
        if query.message:
            try:
                await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
            except telegram.error.BadRequest as e:
                 if "There is no text in the message to edit" in str(e) and query.message:
                    await query.edit_message_caption(caption=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."), reply_markup=None)
                 else:
                    logger.error(f"[AdminInterfaceV8_ArabicFix] Error editing auth fail message (fetch): {e}")
        return

    parts = query.data.split("_")
    time_filter_key = parts[-1]
    if parts[-2] in ["7", "30"] and parts[-3] == "last" and len(parts) > 4: 
        time_filter_key = "_" .join(parts[-3:]) 
        stat_category_str = "_".join(parts[3:-3])
    else: 
        stat_category_str = "_".join(parts[3:-1])
    
    logger.debug(f"[AdminInterfaceV8_ArabicFix] Parsed category: {stat_category_str}, time_filter: {time_filter_key}")
    time_filter_text = process_arabic_text(TIME_FILTERS_DISPLAY.get(time_filter_key, "كل الوقت"))
    stat_category_display_title_map = {
        "usage_overview": "نظرة عامة على الاستخدام",
        "quiz_performance": "أداء الاختبارات",
        "user_interaction": "تفاعل المستخدمين",
        "question_stats": "إحصائيات الأسئلة"
    }
    stat_category_display_title = process_arabic_text(stat_category_display_title_map.get(stat_category_str, stat_category_str.replace("_", " ").title()))
    loading_message_text = process_arabic_text(f"⏳ جاري جلب بيانات {stat_category_display_title} عن فترة: {time_filter_text}...")
    try:
        if query.message:
            await query.edit_message_text(text=loading_message_text, reply_markup=None) # Remove buttons while loading
    except Exception as e:
        logger.error(f"[AdminInterfaceV8_ArabicFix] Error editing loading message: {e}", exc_info=True)

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key, stat_category_display_title)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str, stat_category_display_title: str):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV8_ArabicFix] send_dashboard_stats for {stat_category}, filter {time_filter}, user {user_id}")
    
    text_response = ""
    chart_paths = []
    original_message_id = query.message.message_id if query.message else None
    chat_id = query.message.chat_id if query.message else None
    current_reply_markup = None 

    if not chat_id:
        logger.error("[AdminInterfaceV8_ArabicFix] Cannot determine chat_id in send_dashboard_stats_v4.")
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
            logger.warning(f"[AdminInterfaceV8_ArabicFix] Unknown stat_category: {stat_category}")
            text_response = process_arabic_text(f"فئة الإحصائيات \"{stat_category_display_title}\" غير معروفة.")

        if not text_response and not (chart_paths and any(os.path.exists(p) for p in chart_paths if p)):
             text_response = process_arabic_text(f"لا توجد بيانات لعرضها حالياً لـ {stat_category_display_title} عن فترة {TIME_FILTERS_DISPLAY.get(time_filter, time_filter)}.")

        processed_text_response = process_arabic_text(text_response) # Process the main text response here

        if chart_paths and any(os.path.exists(p) for p in chart_paths if p):
            logger.info(f"Charts found for {stat_category}. Sending photo(s).")
            sent_photo_message = None
            if original_message_id and query.message and query.message.text:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id)
                    logger.info(f"[AdminInterfaceV8_ArabicFix] Deleted original text message {original_message_id} before sending photo.")
                except Exception as del_err:
                    logger.warning(f"[AdminInterfaceV8_ArabicFix] Could not delete original text message {original_message_id}: {del_err}")
            
            media_group = []
            valid_chart_paths = [p for p in chart_paths if p and os.path.exists(p)]

            # Caption for the first image, or for the single image if not a group
            caption_text = process_arabic_text(f"{processed_text_response}\n\n🖼️ {stat_category_display_title} ({process_arabic_text(TIME_FILTERS_DISPLAY.get(time_filter, time_filter))})")

            if len(valid_chart_paths) == 1:
                with open(valid_chart_paths[0], "rb") as photo_file:
                    sent_photo_message = await context.bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption_text, reply_markup=current_reply_markup)
            elif len(valid_chart_paths) > 1:
                for i, chart_path_item in enumerate(valid_chart_paths):
                    with open(chart_path_item, "rb") as photo_file_item:
                        # Only the first photo in a group gets the caption
                        current_caption = caption_text if i == 0 else None
                        media_group.append(InputMediaPhoto(media=photo_file_item.read(), caption=current_caption))
                if media_group:
                    sent_messages = await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                    sent_photo_message = sent_messages[0] # First message in group for reference
                    # Sending reply_markup in a separate message after media group
                    await context.bot.send_message(chat_id=chat_id, text=process_arabic_text("اختر إجراءً آخر أو فترة زمنية جديدة:"), reply_markup=current_reply_markup)
            
            if original_message_id and query.message and not query.message.text: # If original was a photo, try to delete it
                 if sent_photo_message and original_message_id != sent_photo_message.message_id:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id)
                        logger.info(f"[AdminInterfaceV8_ArabicFix] Deleted original photo message {original_message_id}.")
                    except Exception as del_photo_err:
                        logger.warning(f"[AdminInterfaceV8_ArabicFix] Failed to delete original photo message {original_message_id}: {del_photo_err}")

        elif processed_text_response: # Only text, no charts
            logger.info(f"No charts for {stat_category}, sending text only.")
            if query.message:
                try:
                    await query.edit_message_text(text=processed_text_response, reply_markup=current_reply_markup)
                except telegram.error.BadRequest as e:
                    if "Message is not modified" in str(e):
                        logger.info("[AdminInterfaceV8_ArabicFix] Message not modified, content is the same.")
                    elif "There is no text in the message to edit" in str(e) and query.message: # If it was a photo message
                        logger.warning(f"[AdminInterfaceV8_ArabicFix] Cannot edit_message_text (was photo). Deleting and sending new. Msg ID: {query.message.message_id}")
                        await query.message.delete()
                        await context.bot.send_message(chat_id=chat_id, text=processed_text_response, reply_markup=current_reply_markup)
                    else:
                        raise # Re-raise other BadRequest errors
            else: # No query.message, should not happen if callback
                 await context.bot.send_message(chat_id=chat_id, text=processed_text_response, reply_markup=current_reply_markup)

    except Exception as e:
        logger.error(f"[AdminInterfaceV8_ArabicFix] Error in send_dashboard_stats_v4 for {stat_category} ({time_filter}): {e}", exc_info=True)
        error_message_text = process_arabic_text(f"حدث خطأ ما أثناء جلب بيانات {stat_category_display_title}:\n{str(e)}\n\nيرجى المحاولة مرة أخرى أو اختيار فترة مختلفة.")
        # Fallback reply_markup if not set
        if not current_reply_markup:
            fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
            current_reply_markup = get_time_filter_buttons_v4(fetch_base_callback)
        try:
            if query.message and query.message.text: # If original message was text
                await query.edit_message_text(text=error_message_text, reply_markup=current_reply_markup)
            elif query.message: # If original message was not text (e.g. photo) or no text
                await query.message.delete() # Delete the old message (photo or textless)
                await context.bot.send_message(chat_id=chat_id, text=error_message_text, reply_markup=current_reply_markup)
            else: # No query.message, send new message
                await context.bot.send_message(chat_id=chat_id, text=error_message_text, reply_markup=current_reply_markup)
        except Exception as send_err_e:
            logger.critical(f"[AdminInterfaceV8_ArabicFix] CRITICAL: Failed to send detailed error message: {send_err_e}. Sending final fallback.")
            final_fallback_text = process_arabic_text("حدث خطأ حرج. لا يمكن عرض البيانات أو إرسال رسالة خطأ مفصلة.")
            try:
                await context.bot.send_message(chat_id=chat_id, text=final_fallback_text, reply_markup=None) # No buttons on final fallback
            except Exception as final_send_err:
                 logger.critical(f"[AdminInterfaceV8_ArabicFix] CRITICAL: Failed to send even the final fallback message: {final_send_err}")
    finally:
        # Clean up chart files
        for chart_p in chart_paths:
            if chart_p and os.path.exists(chart_p):
                try:
                    os.remove(chart_p)
                    logger.info(f"[AdminInterfaceV8_ArabicFix] Cleaned up chart file: {chart_p}")
                except Exception as e_clean:
                    logger.error(f"[AdminInterfaceV8_ArabicFix] Error cleaning up chart file {chart_p}: {e_clean}")

logger.info("[AdminInterfaceV8_ArabicFix] All function definitions complete.")

# Handlers to be imported by bot.py
admin_stats_command_handler_v4 = CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)
admin_stats_menu_callback_handler_v4 = CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")
admin_stats_fetch_callback_handler_v4 = CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")

