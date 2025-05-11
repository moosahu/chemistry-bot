# admin_interface.py (v5 - Chart Sending and Caption Fix)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
import os

from utils.admin_auth import is_admin as is_admin_original # Renamed to avoid conflict
from database.manager import DB_MANAGER
from config import logger

from .admin_dashboard_display import (
    get_usage_overview_display,
    get_quiz_performance_display,
    get_user_interaction_display,
    get_question_stats_display,
    TIME_FILTERS_DISPLAY,
    process_arabic_text # Import for caption processing if needed
)

STATS_PREFIX_MAIN_MENU = "stats_menu_v4_"
STATS_PREFIX_FETCH = "stats_fetch_v4_"

logger.info("[AdminInterfaceV5_ChartFix] Module loaded.")

async def is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        logger.warning("[AdminInterfaceV5_ChartFix] is_admin: No effective_user found.")
        return False
    user_id = user.id
    logger.info(f"[AdminInterfaceV5_ChartFix] is_admin: Checking admin for user_id: {user_id}")
    if hasattr(DB_MANAGER, 'is_user_admin'):
        try:
            admin_status = DB_MANAGER.is_user_admin(user_id)
            logger.info(f"[AdminInterfaceV5_ChartFix] is_admin: DB_MANAGER returned {admin_status} for {user_id}")
            return admin_status
        except Exception as e:
            logger.error(f"[AdminInterfaceV5_ChartFix] is_admin: DB_MANAGER error for {user_id}: {e}", exc_info=True)
            return False
    logger.warning(f"[AdminInterfaceV5_ChartFix] is_admin: DB_MANAGER.is_user_admin not found. Defaulting to False for {user_id}.")
    return False

def get_time_filter_buttons_v4(stat_category_base_callback: str):
    logger.debug(f"[AdminInterfaceV5_ChartFix] get_time_filter_buttons_v4 with base: {stat_category_base_callback}")
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
    logger.info(f"[AdminInterfaceV5_ChartFix] /adminstats_v4 from user: {user_id}")
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV5_ChartFix] User {user_id} is NOT admin for /adminstats_v4.")
        if update.message:
            await update.message.reply_text(process_arabic_text("عذراً، هذا الأمر مخصص للأدمن فقط."))
        return
    logger.info(f"[AdminInterfaceV5_ChartFix] User {user_id} IS admin. Showing main menu.")
    await show_main_stats_menu_v4(update, context)

async def show_main_stats_menu_v4(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV5_ChartFix] show_main_stats_menu_v4 for user: {user_id}. Query: {query is not None}")
    keyboard = [
        [InlineKeyboardButton(process_arabic_text("📊 نظرة عامة على الاستخدام"), callback_data=f"{STATS_PREFIX_MAIN_MENU}usage_overview")],
        [InlineKeyboardButton(process_arabic_text("📈 أداء الاختبارات"), callback_data=f"{STATS_PREFIX_MAIN_MENU}quiz_performance")],
        [InlineKeyboardButton(process_arabic_text("👥 تفاعل المستخدمين"), callback_data=f"{STATS_PREFIX_MAIN_MENU}user_interaction")],
        [InlineKeyboardButton(process_arabic_text("❓ إحصائيات الأسئلة"), callback_data=f"{STATS_PREFIX_MAIN_MENU}question_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = process_arabic_text("لوحة تحكم إحصائيات الأدمن (v5): اختر فئة لعرضها")
    try:
        if query:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=message_text, reply_markup=reply_markup)
        elif update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV5_ChartFix] Error in show_main_stats_menu_v4: {e}", exc_info=True)

async def stats_menu_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV5_ChartFix] stats_menu_callback from user: {user_id}, data: {query.data}")
    await query.answer()
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV5_ChartFix] User {user_id} is NOT admin for callback: {query.data}")
        try:
            await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
        except Exception as e:
            logger.error(f"[AdminInterfaceV5_ChartFix] Error editing auth fail message: {e}")
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
        await query.edit_message_text(text=message_text_for_edit, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[AdminInterfaceV5_ChartFix] Error editing time filter prompt: {e}", exc_info=True)

async def stats_fetch_callback_handler_v4(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV5_ChartFix] stats_fetch_callback from user: {user_id}, data: {query.data}")
    await query.answer()
    if not await is_admin(update, context):
        logger.warning(f"[AdminInterfaceV5_ChartFix] User {user_id} is NOT admin for fetch callback: {query.data}")
        try:
            await query.edit_message_text(text=process_arabic_text("عذراً، الوصول لهذه الإحصائيات مخصص للأدمن فقط."))
        except Exception as e:
            logger.error(f"[AdminInterfaceV5_ChartFix] Error editing auth fail message (fetch): {e}")
        return

    parts = query.data.split("_")
    time_filter_key = parts[-1]
    if parts[-2] in ["7", "30"] and parts[-3] == "last": # Handles last_7_days, last_30_days
        time_filter_key = parts[-3] + "_" + parts[-2] + "_" + parts[-1]
        stat_category_str = "_".join(parts[3:-3])
    else:
        stat_category_str = "_".join(parts[3:-1])
    
    logger.debug(f"[AdminInterfaceV5_ChartFix] Parsed category: {stat_category_str}, time_filter: {time_filter_key}")
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
        await query.edit_message_text(text=loading_message_text)
    except Exception as e:
        logger.error(f"[AdminInterfaceV5_ChartFix] Error editing loading message: {e}", exc_info=True)

    await send_dashboard_stats_v4(update, context, stat_category_str, time_filter_key, stat_category_display_title)

async def send_dashboard_stats_v4(update: Update, context: CallbackContext, stat_category: str, time_filter: str, stat_category_display_title: str):
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"[AdminInterfaceV5_ChartFix] send_dashboard_stats for {stat_category}, filter {time_filter}, user {user_id}")
    text_response = ""
    chart_paths = [] # Can be a single path or list of paths

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
        logger.warning(f"[AdminInterfaceV5_ChartFix] Unknown stat_category: {stat_category}")
        text_response = process_arabic_text(f"فئة الإحصائيات '{stat_category}' غير معروفة.")

    # Prepare reply markup (time filters for the current category)
    fetch_base_callback = f"{STATS_PREFIX_FETCH}{stat_category}"
    current_reply_markup = get_time_filter_buttons_v4(fetch_base_callback)

    try:
        if chart_paths and any(os.path.exists(p) for p in chart_paths if p):
            logger.info(f"Charts found for {stat_category}. Sending photo(s) with text as caption.")
            
            # Send the main text response first, then the charts
            # Or, if only one chart, send it with the text as caption.
            # For multiple charts, send text, then charts one by one.

            if len(chart_paths) == 1 and chart_paths[0] and os.path.exists(chart_paths[0]):
                # Single chart: send with text_response as caption and full buttons
                with open(chart_paths[0], "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo_file,
                        caption=text_response, # Full stats text as caption
                        parse_mode="Markdown",
                        reply_markup=current_reply_markup
                    )
                # Clean up the original "loading" message
                try:
                    await query.edit_message_text(text=process_arabic_text(f"تم عرض إحصائيات {stat_category_display_title} مع الرسم البياني."), reply_markup=None)
                except Exception as edit_e:
                    logger.warning(f"[AdminInterfaceV5_ChartFix] Could not edit loading message post single chart: {edit_e}")
            else: # Multiple charts or error with single chart path
                # Send text response with buttons first
                await query.edit_message_text(text=text_response, reply_markup=current_reply_markup, parse_mode="Markdown")
                # Then send each chart separately without buttons on them
                for i, chart_p in enumerate(chart_paths):
                    if chart_p and os.path.exists(chart_p):
                        with open(chart_p, "rb") as photo_file:
                            chart_caption = process_arabic_text(f"رسم بياني ({i+1}/{len(chart_paths)}) لـ: {stat_category_display_title}")
                            await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=chart_caption)
                    else:
                        logger.warning(f"Chart path {chart_p} not found for multi-chart send.")
        else: # No charts or charts not found
            if chart_paths: # Paths were given but files not found
                logger.warning(f"Chart paths {chart_paths} provided but files not found.")
                text_response += process_arabic_text("\n\n(تعذر تحميل واحد أو أكثر من الرسوم البيانية)")
            logger.debug(f"No charts to send for {stat_category}. Editing message with text only.")
            await query.edit_message_text(text=text_response, reply_markup=current_reply_markup, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"[AdminInterfaceV5_ChartFix] Error in send_dashboard_stats_v4: {e}", exc_info=True)
        try:
            error_text = process_arabic_text("حدث خطأ أثناء عرض الإحصائيات. يرجى المحاولة مرة أخرى أو اختيار فترة مختلفة.")
            await query.edit_message_text(text=error_text, reply_markup=current_reply_markup) # Allow retry with same buttons
        except Exception as e2:
            logger.error(f"[AdminInterfaceV5_ChartFix] Error in fallback edit_message_text: {e2}", exc_info=True)
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=process_arabic_text("حدث خطأ فادح. يرجى العودة للقائمة الرئيسية والمحاولة."),
                    reply_markup=None
                )
            except Exception as e3:
                logger.critical(f"[AdminInterfaceV5_ChartFix] CRITICAL: Failed to send any error message: {e3}")

logger.info("[AdminInterfaceV5_ChartFix] All function definitions complete.")

# Handlers (assuming these are added to the application in bot.py)
stats_admin_panel_command_handler_v4_obj = CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4)
stats_menu_callback_handler_v4_obj = CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU}")
stats_fetch_callback_handler_v4_obj = CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH}")

