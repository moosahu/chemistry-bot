#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Main script for the Chemistry Quiz Telegram Bot (Modular Version - v17 - post_init DB_MANAGER).

Changes in this version:
- Introduced post_initialize_db_manager to set DB_MANAGER in bot_data after persistence loads.
- Removed direct DB_MANAGER initialization in main() to avoid being overwritten by persistence.
"""

import logging
import sys
import os
import traceback # Import traceback for detailed error logging

# --- Add project root to sys.path ---
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    PicklePersistence,
    CallbackContext,
    JobQueue
)
from telegram import Update

# --- Import Configuration and Core Components ---
quiz_conv_handler = None # Define as None initially
new_admin_tools_loaded = False # Initialize default, will be set by import block
admin_interface_v4_loaded = False # Initialize default

try:
    from config import (
        TELEGRAM_BOT_TOKEN, API_BASE_URL, DATABASE_URL, # Core config
        logger, # Logger instance
        MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Conversation states
    )
    from database.db_setup import get_engine, create_tables # MODIFIED: create_connection to get_engine
    from handlers.common import start_handler, main_menu_callback
    from handlers.common import exam_countdown_callback
    from handlers.study_schedule import (
        study_menu_callback,
        sched_start_callback,
        sched_subj_toggle_callback,
        sched_next_pages_callback,
        sched_default_pages_callback,
        sched_skip_subj_callback,
        sched_cancel_callback,
        sched_dur_callback,
        sched_rest_toggle_callback,
        sched_confirm_callback,
        sched_pages_text_handler,
        study_view_week_callback,
        study_toggle_day_callback,
        study_record_today_callback,
        study_export_pdf_callback,
        study_print_cards_callback,
        study_delete_plan_callback,
        study_delete_confirm_callback,
    )

    try:
        from handlers.quiz import quiz_conv_handler
    except Exception as import_exc:
        if 'logger' in locals():
             logger.critical(f"CRITICAL: Failed to import quiz_conv_handler: {import_exc}", exc_info=True)
        quiz_conv_handler = None

    try:
        from handlers.info import info_conv_handler
        logger.info("Successfully imported info_conv_handler from handlers.info")
    except ImportError:
        logger.warning("Could not import info_conv_handler from handlers.info. Please ensure the file exists and is correct.")
        info_conv_handler = None
    from handlers.stats import stats_conv_handler

    # --- Import New Admin Tools (Edit Messages, Broadcast) ---
    try:
        from handlers.admin_new_tools import (
            start_command as admin_start_command, 
            about_command as admin_about_command,
            help_command as admin_help_command,
            admin_show_tools_menu_callback,
            admin_back_to_start_callback,
            admin_edit_specific_message_callback,
            admin_edit_other_messages_menu_callback,
            received_new_message_text,
            cancel_edit_command,
            admin_broadcast_start_callback,
            received_broadcast_text,
            admin_broadcast_confirm_callback,
            admin_broadcast_cancel_callback,
            cancel_broadcast_command,
            # === NEW ===
            admin_quick_summary_callback,
            admin_search_student_callback,
            search_student_input_handler,
            cancel_search_command,
            admin_export_users_callback,
            admin_broadcast_menu_callback,
            admin_broadcast_grade_callback,
            admin_broadcast_my_students_callback,
            admin_broadcast_my_grade_callback,
            broadcast_grade_selected,
            admin_edit_messages_menu_callback,
            admin_stats_panel_button_callback,
            admin_toggle_my_student_callback,
            admin_my_students_list_callback,
            admin_untag_student_from_list_callback,
            admin_tag_by_grade_callback,
            admin_tag_grade_action_callback,
            admin_grade_students_list_callback,
            admin_grade_toggle_student_callback,
            admin_untag_all_confirm_callback,
            admin_untag_all_execute_callback,
            admin_report_weekly_callback,
            admin_report_monthly_callback,
            admin_report_certificates_callback,
            admin_report_notify_callback,
            admin_report_notify_confirm_callback,
            admin_notify_toggle_callback,
            admin_notify_select_all_callback,
            admin_notify_deselect_all_callback,
            admin_cert_toggle_callback,
            admin_cert_select_all_callback,
            admin_cert_deselect_all_callback,
            admin_report_cert_confirm_callback,
            # Exam Schedule
            admin_exam_schedule_callback,
            admin_exam_status_callback,
            admin_exam_delete_callback,
            admin_exam_delete_confirm_callback,
            admin_exam_add_callback,
            admin_exam_add_input_handler,
            cancel_exam_command,
            # Bot Settings
            admin_bot_settings_callback,
            admin_toggle_deletion_callback,
            admin_toggle_schedule_callback,
            # States
            EDIT_MESSAGE_TEXT, 
            BROADCAST_MESSAGE_TEXT, 
            BROADCAST_CONFIRM,
            SEARCH_STUDENT_INPUT,
            BROADCAST_GRADE_SELECT,
            EXAM_SCHEDULE_INPUT,
        )
        # إضافة استيراد أدوات تصدير بيانات المستخدمين
        from handlers.admin_tools.admin_commands import export_users_command
        from database.manager_definition import DatabaseManager 
        logger.info("Successfully imported new admin tools (edit/broadcast) and DatabaseManager class.")
        new_admin_tools_loaded = True # Set flag based on successful import
    except ImportError as ie_new_admin:
        logger.warning(f"Could not import new admin tools (edit/broadcast) or DatabaseManager class: {ie_new_admin}. New admin functionalities will be unavailable.")
        new_admin_tools_loaded = False
    # --- End Import New Admin Tools ---

    # New Admin Interface (v4) Handlers
    try:
        from handlers.admin_interface import (
            stats_admin_panel_command_handler_v4,
            stats_menu_callback_handler_v4,
            stats_fetch_callback_handler_v4,
            STATS_PREFIX_MAIN_MENU as STATS_PREFIX_MAIN_MENU_V4,
            STATS_PREFIX_FETCH as STATS_PREFIX_FETCH_V4
        )
        logger.info("Successfully imported Admin Interface V4/V7/V8 handlers from handlers.admin_interface.")
        admin_interface_v4_loaded = True
    except ImportError as ie_v4:
        logger.warning(f"Could not import Admin Interface V4/V7/V8 handlers from handlers.admin_interface: {ie_v4}. The new admin dashboard will not be available.")
        admin_interface_v4_loaded = False

    # --- Import Custom Period Report System ---
    custom_report_loaded = False
    try:
        from custom_period_report import custom_report_conv_handler
        logger.info("Successfully imported Custom Period Report system.")
        custom_report_loaded = True
    except ImportError as ie_custom_report:
        logger.warning(f"Could not import Custom Period Report system: {ie_custom_report}. Custom period reports will not be available.")
        custom_report_loaded = False

except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.critical(f"Failed to import core modules: {e}. Bot cannot start.")
    exit(1)
except Exception as e:
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.critical(f"An unexpected error occurred during imports: {e}. Bot cannot start.")
    exit(1)

async def post_initialize_db_manager(application: Application) -> None:
    """
    This function is called after the Application has been initialized,
    including loading data from persistence. It ensures DB_MANAGER is
    freshly initialized in application.bot_data.
    Uses global 'new_admin_tools_loaded', 'DatabaseManager', 'DATABASE_URL', 'logger'.
    """
    logger.info("Executing post_initialize_db_manager to set DB_MANAGER in bot_data...")
    
    current_db_manager_in_bot_data = None # Default to None
    
    # 'new_admin_tools_loaded' is the global flag set during the initial import phase.
    if new_admin_tools_loaded: 
        logger.info("post_initialize_db_manager: Imports for new admin tools were successful. Attempting to init DB_MANAGER.")
        try:
            # Create a new instance of DatabaseManager
            # DatabaseManager class and DATABASE_URL should be in global scope from imports
            db_manager_instance = DatabaseManager(database_url=DATABASE_URL)
            instance_engine = getattr(db_manager_instance, 'engine', None)

            if db_manager_instance and instance_engine is not None:
                current_db_manager_in_bot_data = db_manager_instance
                logger.info(f"post_initialize_db_manager: DatabaseManager initialized/re-initialized successfully. Type: {type(current_db_manager_in_bot_data)}")
            else:
                logger.error("post_initialize_db_manager: Failed to create a valid DatabaseManager instance (or its engine is None). DB_MANAGER will be None in bot_data.")
        except Exception as e:
            logger.error(f"post_initialize_db_manager: Exception during DatabaseManager instantiation: {e}", exc_info=True)
    else:
        logger.warning("post_initialize_db_manager: Initial imports for new admin tools or DatabaseManager class failed. DB_MANAGER will not be initialized.")

    application.bot_data["DB_MANAGER"] = current_db_manager_in_bot_data
    logger.info(f"post_initialize_db_manager: DB_MANAGER in application.bot_data is now type: {type(application.bot_data.get('DB_MANAGER'))}")

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            error_message = "حدث خطأ ما. يرجى المحاولة مرة أخرى لاحقاً."
            # Attempt to use Arabic processing if available
            # try:
            #     from handlers.admin_interface import process_arabic_text
            #     error_message = process_arabic_text(error_message)
            # except ImportError:
            #     pass # Use plain error message
            await context.bot.send_message(chat_id=update.effective_chat.id, text=error_message)
        except Exception as send_error:
            logger.error(f"Failed to send error message to user: {send_error}")

def main() -> None:
    """Start the bot."""
    # global new_admin_tools_loaded, admin_interface_v4_loaded # These are already global

    logger.info("Starting bot...")

    logger.info("Setting up database engine and tables using SQLAlchemy...")
    engine = None
    try:
        engine = get_engine()
        if engine:
            logger.info(f"SQLAlchemy engine created successfully for: {engine.url}")
            create_tables(engine, drop_first=False)
            logger.info("Database tables checked/created successfully via db_setup using SQLAlchemy.")
        else:
            logger.error("Failed to create SQLAlchemy engine. Bot may not function correctly with database features.")
    except Exception as db_exc:
        logger.error(f"Error during initial SQLAlchemy database setup (get_engine or create_tables): {db_exc}", exc_info=True)
    
    # تهيئة نظام الحماية الإداري
    try:
        from admin_security_system import initialize_admin_security
        from admin_commands import admin_conversation_handler, quick_block_command, quick_unblock_command
        
        # ضع معرفات المدراء هنا - يجب تحديثها بالمعرفات الحقيقية
        ADMIN_IDS = [6448526509]  # معرفك الحقيقي
        
        # تهيئة نظام الحماية
        security_manager = initialize_admin_security(ADMIN_IDS)
        logger.info(f"[SECURITY] تم تهيئة نظام الحماية مع {len(ADMIN_IDS)} مدير")
        
    except ImportError as e:
        logger.error(f"[SECURITY] خطأ في استيراد نظام الحماية: {e}. سيعمل البوت بدون حماية إدارية.")
        security_manager = None
    
    persistence = None
    try:
        persistence_dir = os.path.join(project_root, 'persistence')
        os.makedirs(persistence_dir, exist_ok=True)
        persistence_file = os.path.join(persistence_dir, 'bot_conversation_persistence.pkl')
        persistence = PicklePersistence(filepath=persistence_file)
        logger.info(f"PicklePersistence configured at {persistence_file}. All ConversationHandlers should be persistent=False.")
    except Exception as pers_exc:
        logger.error(f"Error configuring persistence: {pers_exc}. Proceeding without persistence.", exc_info=True)
        persistence = None

    job_queue = None
    try:
        job_queue = JobQueue()
        logger.info("JobQueue created.")
    except Exception as jq_exc:
        logger.error(f"Error creating JobQueue: {jq_exc}")
        job_queue = None 

    try:
        app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
        if persistence:
            app_builder = app_builder.persistence(persistence)
            logger.info("Persistence object successfully attached to ApplicationBuilder.")
        else:
            logger.warning("Persistence object is None. Application will be built without persistence. Ensure all ConversationHandlers are persistent=False.")
            
        # Add the post_init hook HERE
        app_builder = app_builder.post_init(post_initialize_db_manager)
        logger.info("post_initialize_db_manager hook added to ApplicationBuilder.")

        if job_queue:
            app_builder = app_builder.job_queue(job_queue)

        application = app_builder.build()
        logger.info("Telegram Application built.")
        
        # The DB_MANAGER initialization block that was previously here has been removed.
        # It's now handled by post_initialize_db_manager after persistence loading.

        if job_queue:
            job_queue.set_application(application)
            logger.info("JobQueue attached to the application.")
        else:
            logger.warning("JobQueue was not created or attached. Timed features will not work.")

    except Exception as app_exc:
        logger.critical(f"Error building Telegram Application: {app_exc}. Bot cannot start.", exc_info=True)
        exit(1)

    # إضافة معالجات التسجيل أولاً قبل أي معالج آخر
    try:
        # استيراد معالجات التسجيل
        from registration import registration_conv_handler, edit_info_conv_handler
        
        # إضافة معالج التسجيل أولاً
        application.add_handler(registration_conv_handler)
        logger.info("Registration conversation handler added successfully.")
        
        # إضافة معالج تعديل المعلومات
        application.add_handler(edit_info_conv_handler)
        logger.info("Edit info conversation handler added successfully.")
    except ImportError as e:
        # محاولة استيراد من المسار الكامل
        try:
            from handlers.registration import registration_conv_handler, edit_info_conv_handler
            
            # إضافة معالج التسجيل أولاً
            application.add_handler(registration_conv_handler)
            logger.info("Registration conversation handler added successfully from handlers.registration.")
            
            # إضافة معالج تعديل المعلومات
            application.add_handler(edit_info_conv_handler)
            logger.info("Edit info conversation handler added successfully from handlers.registration.")
        except ImportError as e2:
            logger.error(f"Error importing registration handlers: {e2}. Registration features will not be available.")

    # إضافة معالجات الإدارة والحماية
    if security_manager:
        try:
            # إضافة معالجات الإدارة
            application.add_handler(admin_conversation_handler)
            application.add_handler(CommandHandler("block", quick_block_command))
            application.add_handler(CommandHandler("unblock", quick_unblock_command))
            logger.info("[SECURITY] تم إضافة معالجات الإدارة والحماية بنجاح")
        except Exception as e:
            logger.error(f"[SECURITY] خطأ في إضافة معالجات الإدارة: {e}")

    # إضافة باقي المعالجات بعد معالجات التسجيل والإدارة
    if new_admin_tools_loaded:
        # تجنب إضافة معالج start لتجنب التعارض مع معالج التسجيل
        application.add_handler(CommandHandler("about", admin_about_command))
        application.add_handler(CommandHandler("help", admin_help_command))
        logger.info("New admin tools command handlers (about, help) added.")
    else:
        # لا نضيف معالج start هنا لأنه تمت إضافته بالفعل في معالج التسجيل
        logger.info("Common start_handler is already handled by registration_conv_handler.")

    if quiz_conv_handler:
        application.add_handler(quiz_conv_handler)
    else:
        logger.warning("quiz_conv_handler was not imported successfully or failed during import, skipping addition.")

    if info_conv_handler:
        application.add_handler(info_conv_handler)
        logger.debug(f"[DEBUG] info_conv_handler added to application: {info_conv_handler}")
    else:
        logger.warning("info_conv_handler was not imported or is None, skipping addition.")

    if stats_conv_handler:
        application.add_handler(stats_conv_handler)
        logger.debug(f"[DEBUG] stats_conv_handler added to application: {stats_conv_handler}")
    else:
        logger.warning("stats_conv_handler is None, skipping addition.")

    if admin_interface_v4_loaded:
        logger.info("Adding New Admin Statistics (V4/V7/V8) handlers (e.g., /adminstats_v4)...")
        application.add_handler(CommandHandler("adminstats_v4", stats_admin_panel_command_handler_v4))
        application.add_handler(CallbackQueryHandler(stats_menu_callback_handler_v4, pattern=f"^{STATS_PREFIX_MAIN_MENU_V4}"))
        application.add_handler(CallbackQueryHandler(stats_fetch_callback_handler_v4, pattern=f"^{STATS_PREFIX_FETCH_V4}"))
        logger.info("New Admin Statistics (V4/V7/V8) handlers added for /adminstats_v4.")
    else:
        logger.warning("New Admin Statistics (V4/V7/V8) handlers were not imported, skipping their addition.")

    # إضافة معالج القائمة الرئيسية بعد معالجات التسجيل
    logger.info("Adding global main_menu_callback handler...")
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^(main_menu|about_bot)$"))
    logger.info("Global main_menu_callback handler added.")
    
    # Exam countdown handler (for students)
    application.add_handler(CallbackQueryHandler(exam_countdown_callback, pattern="^exam_countdown$"))
    logger.info("Exam countdown handler added.")
    
    # إضافة معالج عرض الاختبارات المحفوظة (resume_saved_quiz موجود في quiz_conv_handler)
    try:
        from handlers.quiz import show_saved_quizzes_menu
        application.add_handler(CallbackQueryHandler(show_saved_quizzes_menu, pattern="^show_saved_quizzes$"))
        logger.info("Saved quizzes handler (show_saved_quizzes_menu) added successfully.")
    except ImportError as e:
        logger.warning(f"Could not import saved quizzes handler: {e}. Resume quiz feature will not be available.")

    if new_admin_tools_loaded:
        logger.info("Adding new admin tools (edit/broadcast) ConversationHandlers...")
        edit_message_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_edit_specific_message_callback, pattern=r"^admin_edit_specific_msg_")
            ],
            states={
                EDIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_message_text)],
            },
            fallbacks=[
                CommandHandler("cancel_edit", cancel_edit_command),
                CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"),
                CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern=r"^admin_edit_other_messages_menu$")
            ],
            persistent=False,
            name="edit_message_conversation"
        )
        application.add_handler(edit_message_conv_handler)

        broadcast_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_broadcast_start_callback, pattern=r"^admin_broadcast_start$"),
                CallbackQueryHandler(admin_broadcast_grade_callback, pattern=r"^admin_broadcast_grade$"),
                CallbackQueryHandler(admin_broadcast_my_students_callback, pattern=r"^admin_broadcast_my_students$"),
                CallbackQueryHandler(admin_broadcast_my_grade_callback, pattern=r"^admin_broadcast_my_grade$"),
            ],
            states={
                BROADCAST_GRADE_SELECT: [
                    CallbackQueryHandler(broadcast_grade_selected, pattern=r"^bcast_grade_"),
                ],
                BROADCAST_MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_broadcast_text)],
                BROADCAST_CONFIRM: [
                    CallbackQueryHandler(admin_broadcast_confirm_callback, pattern=r"^admin_broadcast_confirm$"),
                    CallbackQueryHandler(admin_broadcast_cancel_callback, pattern=r"^admin_broadcast_cancel$")
                ]
            },
            fallbacks=[
                CommandHandler("cancel_broadcast", cancel_broadcast_command),
                CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$")
            ],
            persistent=False,
            name="broadcast_conversation"
        )
        application.add_handler(broadcast_conv_handler)

        # === NEW: بحث عن طالب ===
        search_student_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(admin_search_student_callback, pattern=r"^admin_search_student$"),
            ],
            states={
                SEARCH_STUDENT_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, search_student_input_handler),
                ],
            },
            fallbacks=[
                CommandHandler("cancel_search", cancel_search_command),
                CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"),
            ],
            persistent=False,
            name="search_student_conversation"
        )
        application.add_handler(search_student_conv_handler)

        # Add other admin tools handlers
        application.add_handler(CallbackQueryHandler(admin_show_tools_menu_callback, pattern=r"^admin_show_tools_menu$"))
        application.add_handler(CallbackQueryHandler(admin_back_to_start_callback, pattern=r"^admin_back_to_start$"))
        application.add_handler(CallbackQueryHandler(admin_edit_other_messages_menu_callback, pattern=r"^admin_edit_other_messages_menu$"))
        # === NEW handlers ===
        application.add_handler(CallbackQueryHandler(admin_quick_summary_callback, pattern=r"^admin_quick_summary$"))
        application.add_handler(CallbackQueryHandler(admin_export_users_callback, pattern=r"^admin_export_users$"))
        application.add_handler(CallbackQueryHandler(admin_broadcast_menu_callback, pattern=r"^admin_broadcast_menu$"))
        application.add_handler(CallbackQueryHandler(admin_edit_messages_menu_callback, pattern=r"^admin_edit_messages_menu$"))
        application.add_handler(CallbackQueryHandler(admin_stats_panel_button_callback, pattern=r"^stats_admin_panel_v4$"))
        application.add_handler(CallbackQueryHandler(admin_toggle_my_student_callback, pattern=r"^toggle_my_student_"))
        # === طلابي handlers ===
        application.add_handler(CallbackQueryHandler(admin_my_students_list_callback, pattern=r"^admin_my_students_list$"))
        application.add_handler(CallbackQueryHandler(admin_my_students_list_callback, pattern=r"^my_students_page_"))
        application.add_handler(CallbackQueryHandler(admin_untag_student_from_list_callback, pattern=r"^untag_student_"))
        application.add_handler(CallbackQueryHandler(admin_tag_by_grade_callback, pattern=r"^admin_tag_by_grade$"))
        application.add_handler(CallbackQueryHandler(admin_tag_grade_action_callback, pattern=r"^tag_grade_"))
        application.add_handler(CallbackQueryHandler(admin_tag_grade_action_callback, pattern=r"^untag_grade_"))
        application.add_handler(CallbackQueryHandler(admin_grade_students_list_callback, pattern=r"^grade_students_"))
        application.add_handler(CallbackQueryHandler(admin_grade_toggle_student_callback, pattern=r"^gtoggle_"))
        application.add_handler(CallbackQueryHandler(admin_untag_all_confirm_callback, pattern=r"^admin_untag_all_confirm$"))
        application.add_handler(CallbackQueryHandler(admin_untag_all_execute_callback, pattern=r"^admin_untag_all_execute$"))
        # === Report, Certificates & Notifications handlers ===
        application.add_handler(CallbackQueryHandler(admin_report_weekly_callback, pattern=r"^admin_report_weekly$"))
        application.add_handler(CallbackQueryHandler(admin_report_monthly_callback, pattern=r"^admin_report_monthly$"))
        application.add_handler(CallbackQueryHandler(admin_report_certificates_callback, pattern=r"^admin_report_certificates$"))
        application.add_handler(CallbackQueryHandler(admin_report_notify_callback, pattern=r"^admin_report_notify$"))
        application.add_handler(CallbackQueryHandler(admin_report_notify_confirm_callback, pattern=r"^admin_report_notify_confirm$"))
        application.add_handler(CallbackQueryHandler(admin_notify_toggle_callback, pattern=r"^ntoggle_"))
        application.add_handler(CallbackQueryHandler(admin_notify_select_all_callback, pattern=r"^notify_select_all$"))
        application.add_handler(CallbackQueryHandler(admin_notify_deselect_all_callback, pattern=r"^notify_deselect_all$"))
        application.add_handler(CallbackQueryHandler(admin_cert_toggle_callback, pattern=r"^ctoggle_"))
        application.add_handler(CallbackQueryHandler(admin_cert_select_all_callback, pattern=r"^cert_select_all$"))
        application.add_handler(CallbackQueryHandler(admin_cert_deselect_all_callback, pattern=r"^cert_deselect_all$"))
        application.add_handler(CallbackQueryHandler(admin_report_cert_confirm_callback, pattern=r"^admin_report_cert_confirm$"))
        # === Exam Schedule handlers ===
        application.add_handler(CallbackQueryHandler(admin_exam_schedule_callback, pattern=r"^admin_exam_schedule$"))
        application.add_handler(CallbackQueryHandler(admin_exam_status_callback, pattern=r"^exam_status_"))
        application.add_handler(CallbackQueryHandler(admin_exam_delete_callback, pattern=r"^exam_delete_\d+$"))
        application.add_handler(CallbackQueryHandler(admin_exam_delete_confirm_callback, pattern=r"^exam_del_yes_"))
        # Exam add conversation handler
        exam_add_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_exam_add_callback, pattern=r"^admin_exam_add$")],
            states={
                EXAM_SCHEDULE_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_exam_add_input_handler),
                ],
            },
            fallbacks=[
                CommandHandler("cancel_exam", cancel_exam_command),
                CallbackQueryHandler(admin_exam_schedule_callback, pattern=r"^admin_exam_schedule$"),
            ],
            persistent=False,
            name="exam_add_conversation"
        )
        application.add_handler(exam_add_conv_handler)
        # Bot Settings handlers
        application.add_handler(CallbackQueryHandler(admin_bot_settings_callback, pattern=r"^admin_bot_settings$"))
        application.add_handler(CallbackQueryHandler(admin_toggle_deletion_callback, pattern=r"^admin_toggle_deletion$"))
        application.add_handler(CallbackQueryHandler(admin_toggle_schedule_callback, pattern=r"^admin_toggle_schedule$"))
        # Study Schedule handlers — مدمج (تتبع + بطاقات)
        application.add_handler(CallbackQueryHandler(study_menu_callback, pattern=r"^study_menu$"))
        application.add_handler(CallbackQueryHandler(sched_start_callback, pattern=r"^sched_start$"))
        application.add_handler(CallbackQueryHandler(sched_subj_toggle_callback, pattern=r"^sched_subj_\d+$"))
        application.add_handler(CallbackQueryHandler(sched_next_pages_callback, pattern=r"^sched_next_pages$"))
        application.add_handler(CallbackQueryHandler(sched_default_pages_callback, pattern=r"^sched_def_\d+$"))
        application.add_handler(CallbackQueryHandler(sched_skip_subj_callback, pattern=r"^sched_skip_subj$"))
        application.add_handler(CallbackQueryHandler(sched_cancel_callback, pattern=r"^sched_cancel$"))
        application.add_handler(CallbackQueryHandler(sched_dur_callback, pattern=r"^sched_dur_\d+$"))
        application.add_handler(CallbackQueryHandler(sched_rest_toggle_callback, pattern=r"^sched_rest_\d$"))
        application.add_handler(CallbackQueryHandler(sched_confirm_callback, pattern=r"^sched_confirm$"))
        # التتبع الأسبوعي
        application.add_handler(CallbackQueryHandler(study_view_week_callback, pattern=r"^study_view_week_\d+$"))
        application.add_handler(CallbackQueryHandler(study_toggle_day_callback, pattern=r"^study_toggle_\d+_w\d+$"))
        application.add_handler(CallbackQueryHandler(study_record_today_callback, pattern=r"^study_record_today$"))
        application.add_handler(CallbackQueryHandler(study_export_pdf_callback, pattern=r"^study_export_pdf$"))
        application.add_handler(CallbackQueryHandler(study_print_cards_callback, pattern=r"^study_print_cards$"))
        application.add_handler(CallbackQueryHandler(study_delete_plan_callback, pattern=r"^study_delete_plan$"))
        application.add_handler(CallbackQueryHandler(study_delete_confirm_callback, pattern=r"^study_delete_confirm$"))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, sched_pages_text_handler
        ), group=2)
        logger.info("Study schedule handlers added.")
        # noop handler for page number display
        async def noop_callback(update, context):
            await update.callback_query.answer()
        application.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))

        # Add export users command handler if available
        try:
            application.add_handler(CommandHandler("export_users", export_users_command))
            logger.info("Export users command handler added.")
        except NameError:
            logger.warning("export_users_command not found, skipping addition.")

        logger.info("New admin tools (edit/broadcast) ConversationHandlers and related handlers added.")
    else:
        logger.warning("New admin tools (edit/broadcast) were not imported, skipping their addition.")

    # Add error handler
    application.add_error_handler(error_handler)

    # --- Setup Final Weekly Reports System ---
    logger.info("Setting up Final Weekly Reports System...")
    try:
        from final_bot_integration import setup_final_reporting_system, add_final_admin_report_commands
        
        final_reporting_system = setup_final_reporting_system()
        
        if final_reporting_system:
            final_reporting_system.start_scheduler()
            add_final_admin_report_commands(application, final_reporting_system)
            logger.info("✅ Final Weekly Reports System activated successfully")
            logger.info("📊 النظام النهائي يعمل بدون مشاكل الخطوط العربية")
            logger.info("🎯 الأوامر المتاحة: /final_status, /final_generate, /final_analytics")
        else:
            logger.error("❌ Failed to initialize Final Weekly Reports System")
            
    except ImportError as ie:
        logger.warning(f"Could not import Final Weekly Reports System: {ie}. Final reports will not be available.")
    except Exception as e:
        logger.error(f"Error setting up Final Weekly Reports System: {e}", exc_info=True)

    # --- Setup Custom Period Report System ---
    if custom_report_loaded:
        logger.info("Adding Custom Period Report ConversationHandler...")
        try:
            application.add_handler(custom_report_conv_handler)
            logger.info("✅ Custom Period Report System activated successfully")
            logger.info("📊 التقارير المخصصة متاحة الآن")
            logger.info("🎯 استخدم الأمر: /custom_report")
        except Exception as e:
            logger.error(f"Error adding Custom Period Report handler: {e}", exc_info=True)
    else:
        logger.warning("Custom Period Report System was not imported, skipping addition.")

    # Run the bot
    logger.info("Starting bot polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as run_exc:
        logger.critical(f"Critical error during bot polling: {run_exc}", exc_info=True)
        exit(1)

if __name__ == '__main__':
    main()
