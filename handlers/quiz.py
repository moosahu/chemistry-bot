# -*- coding: utf-8 -*-
"""Conversation handler for the quiz selection and execution flow."""

import logging
import math
import random # لاستخدامها في خلط الأسئلة إذا لزم الأمر
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler
)

from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_RANDOM, QUIZ_TYPE_CHAPTER, QUIZ_TYPE_UNIT, QUIZ_TYPE_ALL, # تأكد من وجود هذه الثوابت في config.py
    DEFAULT_QUESTION_TIME_LIMIT # تأكد من وجود هذا الثابت في config.py
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string # تأكد من وجود get_quiz_type_string
from utils.api_client import fetch_from_api # أو أي طريقة تستخدمها لجلب الأسئلة
from handlers.common import create_main_menu_keyboard, main_menu_callback
from .quiz_logic import QuizLogic # استيراد كلاس QuizLogic

ITEMS_PER_PAGE = 6 # لتقسيم الخيارات إلى صفحات إذا لزم الأمر

# --- وظائف مساعدة لإنشاء لوحات المفاتيح ---

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل", callback_data=f"quiz_type_{QUIZ_TYPE_RANDOM}")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        # يمكنك إضافة المزيد من أنواع الاختبارات هنا
        # [InlineKeyboardButton("챕터별 퀴즈", callback_data=f"quiz_type_{QUIZ_TYPE_CHAPTER}")],
        # [InlineKeyboardButton("전체 범위 퀴즈", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_quiz_scope_keyboard(scopes: list, quiz_type: str, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page
    
    for i in range(start_index, min(end_index, len(scopes))):
        scope = scopes[i]
        # افترض أن scope هو قاموس يحتوي على id و name
        keyboard.append([InlineKeyboardButton(scope['name'], callback_data=f"quiz_scope_specific_{quiz_type}_{scope['id']}")])

    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_scope_page_{quiz_type}_{current_page - 1}"))
    if end_index < len(scopes):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_scope_page_{quiz_type}_{current_page + 1}"))
    
    if pagination_buttons:
        keyboard.append(pagination_buttons)

    keyboard.append([InlineKeyboardButton("🌍 كل النطاقات (لهذا النوع)", callback_data=f"quiz_scope_all_{quiz_type}")])
    keyboard.append([InlineKeyboardButton("🔙 اختيار نوع الاختبار", callback_data=f"quiz_type_back")])
    return InlineKeyboardMarkup(keyboard)

def create_question_count_keyboard(max_questions: int, quiz_type: str, scope_id: str = None) -> InlineKeyboardMarkup:
    counts = [1, 5, 10, 20, min(max_questions, 50)] # أعداد مقترحة
    if max_questions > 0 and max_questions not in counts:
        counts.append(max_questions) # إضافة الحد الأقصى إذا لم يكن موجوداً وكان معقولاً
    counts = sorted(list(set(c for c in counts if c <= max_questions and c > 0))) # إزالة المكرر والفرز والتأكد من أنها ضمن الحدود

    keyboard = []
    row = []
    for count in counts:
        row.append(InlineKeyboardButton(str(count), callback_data=f"num_questions_{count}"))
        if len(row) == 3: # 3 أزرار في كل صف
            keyboard.append(row)
            row = []
    if row: # إضافة أي أزرار متبقية
        keyboard.append(row)
    
    if max_questions > counts[-1] if counts else max_questions > 0:
         keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data=f"num_questions_all")])

    keyboard.append([InlineKeyboardButton("🔙 اختيار النطاق/النوع", callback_data=f"quiz_count_back_{quiz_type}_{scope_id if scope_id else ''}")])
    return InlineKeyboardMarkup(keyboard)

# --- معالجات حالات المحادثة ---

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu via callback.")
    keyboard = create_quiz_type_keyboard()
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
    return SELECT_QUIZ_TYPE

async def select_quiz_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    callback_data = query.data
    if callback_data == "main_menu":
        await main_menu_callback(update, context, from_quiz=True)
        return ConversationHandler.END # العودة إلى القائمة الرئيسية وإنهاء محادثة الاختبار
    if callback_data == "quiz_type_back": # للعودة من اختيار النطاق إلى اختيار النوع
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_type_key = callback_data.split('_')[-1]
    context.user_data["selected_quiz_type_key"] = quiz_type_key
    # افترض أن لديك دالة لجلب اسم العرض للنوع، أو استخدم المفتاح مباشرة
    quiz_type_display_name = get_quiz_type_string(quiz_type_key) # تأكد أن هذه الدالة موجودة في helpers
    context.user_data["selected_quiz_type_display_name"] = quiz_type_display_name
    logger.info(f"User {user_id} selected quiz type: {quiz_type_key} ({quiz_type_display_name})")

    if quiz_type_key == QUIZ_TYPE_RANDOM or quiz_type_key == QUIZ_TYPE_ALL: # أنواع لا تتطلب نطاقاً محدداً
        # جلب الأسئلة مباشرة
        # لاستخدام الـ API:
        # api_endpoint = "questions/random" if quiz_type_key == QUIZ_TYPE_RANDOM else f"questions/all?type={quiz_type_key}"
        # questions_data = await fetch_from_api(api_endpoint, params={'limit': 200}) # حد أعلى للأسئلة
        # Placeholder: استخدم بيانات أسئلة وهمية إذا لم يكن الـ API جاهزاً
        logger.debug(f"[API] Fetching data for quiz type: {quiz_type_key}")
        questions_data = await fetch_from_api(f"questions/random?quiz_type={quiz_type_key}", params={'limit': 200})
        
        if not questions_data:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذا النوع حالياً.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["questions_for_quiz"] = questions_data
        max_questions = len(questions_data)
        logger.info(f"Fetched {max_questions} total questions for {quiz_type_display_name}.")
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name}':", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    
    elif quiz_type_key == QUIZ_TYPE_UNIT or quiz_type_key == QUIZ_TYPE_CHAPTER:
        # جلب النطاقات (الوحدات/الفصول)
        # api_endpoint = "units" if quiz_type_key == QUIZ_TYPE_UNIT else "chapters"
        # scopes = await fetch_from_api(api_endpoint)
        # Placeholder:
        logger.debug(f"[API] Fetching scopes for quiz type: {quiz_type_key}")
        scopes = await fetch_from_api(f"scopes?type={quiz_type_key}") # افترض أن هذا يجلب قائمة بالوحدات أو الفصول
        
        if not scopes:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد نطاقات (وحدات/فصول) متاحة لهذا النوع حالياً.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        
        context.user_data["available_scopes"] = scopes
        context.user_data["current_scope_page"] = 0
        keyboard = create_quiz_scope_keyboard(scopes, quiz_type_key, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر نطاقاً لاختبار '{quiz_type_display_name}':", reply_markup=keyboard)
        return SELECT_QUIZ_SCOPE
    else:
        logger.warning(f"Unknown quiz type key: {quiz_type_key}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

async def handle_scope_pagination(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    # callback_data=f"quiz_scope_page_{quiz_type}_{current_page + 1}"
    parts = query.data.split('_')
    quiz_type_key = parts[3]
    page = int(parts[4])

    scopes = context.user_data.get("available_scopes", [])
    context.user_data["current_scope_page"] = page
    keyboard = create_quiz_scope_keyboard(scopes, quiz_type_key, page)
    quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر نطاقاً لاختبار '{quiz_type_display_name}' (صفحة {page + 1}):", reply_markup=keyboard)
    return SELECT_QUIZ_SCOPE

async def select_quiz_scope_all(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    quiz_type_key = query.data.split('_')[-1]
    context.user_data["selected_scope_id"] = "all"
    context.user_data["selected_scope_name"] = "كل النطاقات"
    quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
    logger.info(f"User {user_id} selected all scopes for quiz type {quiz_type_key}")

    # جلب جميع الأسئلة لهذا النوع
    # api_endpoint = f"questions/all?type={quiz_type_key}" # أو ما يناسب الـ API الخاص بك
    # questions_data = await fetch_from_api(api_endpoint, params={'limit': 500}) # حد أعلى
    logger.debug(f"[API] Fetching all questions for quiz type: {quiz_type_key}")
    questions_data = await fetch_from_api(f"questions/all_by_type?quiz_type={quiz_type_key}", params={'limit': 500})

    if not questions_data:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد أسئلة متاحة لهذا النطاق حالياً.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE # العودة لاختيار النوع

    context.user_data["questions_for_quiz"] = questions_data
    max_questions = len(questions_data)
    keyboard = create_question_count_keyboard(max_questions, quiz_type_key, "all")
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name} - كل النطاقات':", reply_markup=keyboard)
    return ENTER_QUESTION_COUNT

async def select_quiz_scope_specific(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    # callback_data=f"quiz_scope_specific_{quiz_type}_{scope['id']}"
    parts = query.data.split('_')
    quiz_type_key = parts[3]
    scope_id = parts[4]
    
    scopes = context.user_data.get("available_scopes", [])
    selected_scope = next((s for s in scopes if str(s.get('id')) == str(scope_id)), None)
    scope_name = selected_scope['name'] if selected_scope else f"نطاق {scope_id}"
    
    context.user_data["selected_scope_id"] = scope_id
    context.user_data["selected_scope_name"] = scope_name
    quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
    logger.info(f"User {user_id} selected scope {scope_id} ({scope_name}) for quiz type {quiz_type_key}")

    # جلب الأسئلة لهذا النطاق المحدد
    # api_endpoint = f"questions?type={quiz_type_key}&scope_id={scope_id}"
    # questions_data = await fetch_from_api(api_endpoint, params={'limit': 200})
    logger.debug(f"[API] Fetching questions for quiz type: {quiz_type_key}, scope: {scope_id}")
    questions_data = await fetch_from_api(f"questions/by_scope?quiz_type={quiz_type_key}&scope_id={scope_id}", params={'limit': 200})

    if not questions_data:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة لـ '{scope_name}' حالياً.", reply_markup=create_quiz_scope_keyboard(scopes, quiz_type_key, context.user_data.get("current_scope_page",0)))
        return SELECT_QUIZ_SCOPE # العودة لاختيار النطاق

    context.user_data["questions_for_quiz"] = questions_data
    max_questions = len(questions_data)
    keyboard = create_question_count_keyboard(max_questions, quiz_type_key, scope_id)
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار '{quiz_type_display_name} - {scope_name}':", reply_markup=keyboard)
    return ENTER_QUESTION_COUNT

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    callback_data = query.data
    quiz_type_key = context.user_data.get("selected_quiz_type_key")
    scope_id = context.user_data.get("selected_scope_id")

    if callback_data.startswith("quiz_count_back_"):
        # العودة إلى اختيار النطاق أو النوع
        if scope_id is not None and quiz_type_key not in [QUIZ_TYPE_RANDOM, QUIZ_TYPE_ALL]:
            scopes = context.user_data.get("available_scopes", [])
            current_page = context.user_data.get("current_scope_page", 0)
            keyboard = create_quiz_scope_keyboard(scopes, quiz_type_key, current_page)
            quiz_type_display_name = context.user_data.get("selected_quiz_type_display_name", quiz_type_key)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر نطاقاً لاختبار '{quiz_type_display_name}':", reply_markup=keyboard)
            return SELECT_QUIZ_SCOPE
        else:
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE

    num_questions_str = callback_data.split('_')[-1]
    questions_for_quiz_pool = context.user_data.get("questions_for_quiz", [])
    max_available_questions = len(questions_for_quiz_pool)

    if num_questions_str == "all":
        num_questions_to_ask = max_available_questions
    else:
        try:
            num_questions_to_ask = int(num_questions_str)
            if not (0 < num_questions_to_ask <= max_available_questions):
                logger.warning(f"User {user_id} selected invalid number of questions: {num_questions_to_ask}. Max: {max_available_questions}")
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عدد أسئلة غير صالح. يرجى اختيار بين 1 و {max_available_questions}.", reply_markup=create_question_count_keyboard(max_available_questions, quiz_type_key, scope_id))
                return ENTER_QUESTION_COUNT 
        except ValueError:
            logger.error(f"Invalid number of questions callback: {callback_data}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=create_main_menu_keyboard(user_id))
            return QUIZ_MENU 

    if num_questions_to_ask <= 0:
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عدد الأسئلة غير صالح. يرجى اختيار عدد أكبر من صفر.", reply_markup=create_question_count_keyboard(max_available_questions, quiz_type_key, scope_id))
        return ENTER_QUESTION_COUNT

    context.user_data["num_questions_to_ask"] = num_questions_to_ask
    logger.info(f"User {user_id} confirmed {num_questions_to_ask} questions for quiz type {quiz_type_key} (scope: {scope_id}).")

    # تحديد الأسئلة النهائية للاختبار (خلط واختيار العدد المطلوب)
    final_questions_for_quiz = random.sample(questions_for_quiz_pool, k=num_questions_to_ask) if questions_for_quiz_pool else []
    context.user_data["final_questions_for_quiz"] = final_questions_for_quiz

    # *** إنشاء كائن QuizLogic بالوسائط الصحيحة ***
    quiz_logic_instance = QuizLogic(
        context=context,
        bot_instance=context.bot, # يمكن لـ QuizLogic الحصول عليه من context إذا أردت
        user_id=user_id,
        quiz_type=context.user_data.get("selected_quiz_type_key"), # المفتاح الفعلي للنوع
        questions_data=final_questions_for_quiz, # قائمة الأسئلة الفعلية للاختبار
        total_questions=num_questions_to_ask,
        question_time_limit=context.bot_data.get("DEFAULT_QUESTION_TIME_LIMIT", DEFAULT_QUESTION_TIME_LIMIT) # استخدام الثابت من config
    )
    context.user_data["quiz_logic_instance"] = quiz_logic_instance
    logger.info(f"QuizLogic instance created for quiz {quiz_logic_instance.quiz_id}, user {user_id}")

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"👍 ممتاز! سيتم بدء اختبار بـ {num_questions_to_ask} سؤال.", reply_markup=None)
    
    # بدء الاختبار عن طريق استدعاء دالة من كائن QuizLogic
    # هذه الدالة يجب أن تعيد الحالة التالية في المحادثة
    next_state = await quiz_logic_instance.start_quiz(update) # تمرير update إذا كانت QuizLogic تحتاجه
    return next_state # يجب أن تكون هذه TAKING_QUIZ أو END من config.py

async def handle_quiz_answer_wrapper(update: Update, context: CallbackContext) -> int:
    quiz_logic_instance = context.user_data.get("quiz_logic_instance")
    if not quiz_logic_instance:
        logger.error(f"QuizLogic instance not found for user {update.effective_user.id} in handle_quiz_answer_wrapper.")
        query = update.callback_query
        if query:
            await query.answer("عذراً، حدث خطأ في الاختبار. يرجى البدء من جديد.", show_alert=True)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ ما. يرجى بدء الاختبار من جديد.", reply_markup=create_main_menu_keyboard(update.effective_user.id))
        else:
            await safe_send_message(context.bot, update.effective_chat.id, "حدث خطأ ما. يرجى بدء الاختبار من جديد.", reply_markup=create_main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END
    
    # استدعاء دالة معالجة الإجابة من كائن QuizLogic
    # هذه الدالة يجب أن تعيد الحالة التالية أو END
    next_state = await quiz_logic_instance.handle_answer(update, context)
    return next_state

async def cancel_quiz_selection(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled quiz selection/test.")
    await safe_send_message(context.bot, chat_id=update.effective_chat.id, text="تم إلغاء عملية اختيار/إجراء الاختبار.", reply_markup=create_main_menu_keyboard(user_id))
    
    # تنظيف أي بيانات مستخدم متعلقة بالاختبار إذا لزم الأمر
    keys_to_clear = ["selected_quiz_type_key", "selected_quiz_type_display_name", 
                     "available_scopes", "current_scope_page", "selected_scope_id", 
                     "selected_scope_name", "questions_for_quiz", "num_questions_to_ask",
                     "final_questions_for_quiz", "quiz_logic_instance"]
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]
            
    return ConversationHandler.END # إنهاء محادثة الاختبار والعودة

# --- تعريف معالج المحادثة للاختبار ---
quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_start$")],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_.+$"),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$") # للعودة للقائمة الرئيسية
        ],
        SELECT_QUIZ_SCOPE: [
            CallbackQueryHandler(select_quiz_scope_all, pattern="^quiz_scope_all_.+$"),
            CallbackQueryHandler(select_quiz_scope_specific, pattern="^quiz_scope_specific_.+_.+$"),
            CallbackQueryHandler(handle_scope_pagination, pattern="^quiz_scope_page_.+_.+$"),
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back$") # للعودة لاختيار النوع
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count, pattern="^num_questions_.+$"),
            CallbackQueryHandler(enter_question_count, pattern="^quiz_count_back_.+$") # للعودة من اختيار العدد
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer_wrapper, pattern="^ans_.+_.+$") # معالجة الإجابات
            # يمكنك إضافة معالجات أخرى هنا (مثل تخطي السؤال، أوامر خاصة أثناء الاختبار)
        ],
        # SHOWING_RESULTS: [] # يتم التعامل معها الآن داخل QuizLogic
    },
    fallbacks=[
        CommandHandler("cancel", cancel_quiz_selection), # أمر لإلغاء الاختبار في أي وقت
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"), # كخيار احتياطي للعودة للقائمة الرئيسية
        CommandHandler("start", main_menu_callback) # للتعامل مع /start أثناء المحادثة
    ],
    map_to_parent={
        # إذا انتهى الاختبار وعاد MAIN_MENU، ينتقل إلى حالة MAIN_MENU في المحادثة الرئيسية
        MAIN_MENU: MAIN_MENU, # افترض أن MAIN_MENU هو حالة في محادثة رئيسية (إذا كانت موجودة)
        END: END # لإنهاء هذه المحادثة والعودة للمستوى الأعلى
    },
    per_message=False,
    name="quiz_conversation",
    # persistent=True # فكر في موضوع الاستمرارية وكيفية إدارته
)

logger.info("handlers/quiz.py loaded successfully with updated quiz_conv_handler.")

