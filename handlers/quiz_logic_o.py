"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (Modified to import DB_MANAGER directly)
# v2: Fixes for filter_id in DB session and NoneType error in show_results
# v3: Enhanced support for image questions and image options

import asyncio
import logging
import time
import uuid 
import telegram # For telegram.error types
from datetime import datetime, timezone 
import json
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 

from config import logger, TAKING_QUIZ, END, MAIN_MENU, SHOWING_RESULTS # SHOWING_RESULTS is used by this module
from utils.helpers import safe_send_message, safe_edit_message_text, safe_edit_message_caption, remove_job_if_exists

# +++ MODIFICATION: Import DB_MANAGER directly +++
from database.manager import DB_MANAGER
# +++++++++++++++++++++++++++++++++++++++++++++++

MIN_OPTIONS_PER_QUESTION = 2
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")

def is_image_url(url_string: str) -> bool:
    if not isinstance(url_string, str):
        return False
    return (url_string.startswith("http://") or url_string.startswith("https://")) and \
           any(url_string.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح"]

    def __init__(self, user_id, chat_id, questions, quiz_name,
                 quiz_type_for_db_log, quiz_scope_id, total_questions_for_db_log,
                 time_limit_per_question, quiz_instance_id_for_logging):
        
        self.user_id = user_id
        self.chat_id = chat_id
        self.questions_data = questions if questions is not None else []
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        
        self.quiz_type_for_db = quiz_type_for_db_log
        self.quiz_scope_id_for_db = quiz_scope_id 
        self.total_questions_for_db = total_questions_for_db_log

        # تعيين وقت السؤال إلى 3 دقائق (180 ثانية) بغض النظر عن القيمة المرسلة
        self.question_time_limit = 180
        self.quiz_id = quiz_instance_id_for_logging 
        
        self.db_manager = DB_MANAGER
        
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None
        self.last_question_message_id = None # ID of the main question text/image message
        self.sent_option_image_message_ids = [] # IDs of messages sent for image options
        self.active = False
        self.db_quiz_session_id = None

        if not self.db_manager:
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: Imported DB_MANAGER is None! DB ops will fail.")
        
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}).")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, QuizName: \t'{self.quiz_name}'\t, ActualNumQs: {self.total_questions}.")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {self.user_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc)
        self.total_questions = len(self.questions_data)

        if self.db_manager:
            try:
                scope_id_for_db_call = self.quiz_scope_id_for_db
                if isinstance(scope_id_for_db_call, str) and scope_id_for_db_call.lower() == "all":
                    scope_id_for_db_call = None 
                elif isinstance(scope_id_for_db_call, str):
                    try: scope_id_for_db_call = int(scope_id_for_db_call)
                    except ValueError: 
                        logger.error(f"[QuizLogic {self.quiz_id}] Invalid quiz_scope_id_for_db \t'{self.quiz_scope_id_for_db}'\t. Setting to None.")
                        scope_id_for_db_call = None
                
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id, quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=scope_id_for_db_call, quiz_name=self.quiz_name,
                    total_questions=self.total_questions_for_db, start_time=self.quiz_actual_start_time_dt,
                    score=0, initial_percentage=0.0, initial_time_taken_seconds=0)
                if self.db_quiz_session_id: logger.info(f"[QuizLogic {self.quiz_id}] Quiz session logged to DB: {self.db_quiz_session_id}")
                else: logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB.")
            except Exception as e: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz start: {e}", exc_info=True)
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager unavailable. Cannot log quiz start.")

        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic {self.quiz_id}] No questions. Ending quiz.")
            msg_id = update.callback_query.message.message_id if update and update.callback_query else None
            text = "عذراً، لا توجد أسئلة لبدء هذا الاختبار."
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]) # This should be handled by quiz.py to end conv
            if msg_id: await safe_edit_message_text(bot, self.chat_id, msg_id, text, kbd)
            else: await safe_send_message(bot, self.chat_id, text, kbd)
            await self.cleanup_quiz_data(context, self.user_id, "no_questions_on_start") 
            return END # Signal to quiz.py that conversation should end or go to a fallback
        
        return await self.send_question(bot, context, update)
    
    def _create_display_options_and_keyboard(self, options_from_api: list):
        keyboard_buttons = []
        displayable_options = [] 
        option_image_counter = 0

        for i, option_data in enumerate(options_from_api):
            option_id = option_data.get("option_id") 
            option_content = option_data.get("option_text")
            
            button_text_for_keyboard = ""
            display_text_for_answer_log = ""
            is_image_option_flag = False

            if is_image_url(option_content):
                is_image_option_flag = True
                display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter] if option_image_counter < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter + 1}"
                button_text_for_keyboard = f"اختر الخيار المصور: {display_label}"
                display_text_for_answer_log = f"صورة ({display_label})"
                option_image_counter += 1
            elif isinstance(option_content, str):
                button_text_for_keyboard = option_content
                display_text_for_answer_log = option_content
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Option content is not string/URL: {option_content}. Using placeholder.")
                button_text_for_keyboard = f"خيار {i+1} (بيانات غير صالحة)"
                display_text_for_answer_log = button_text_for_keyboard
            
            button_text_final = button_text_for_keyboard.strip()
            if not button_text_final: button_text_final = f"خيار {i+1}"
            if len(button_text_final.encode('utf-8')) > 60:
                temp_bytes = button_text_final.encode('utf-8')[:57]
                button_text_final = temp_bytes.decode('utf-8', 'ignore') + "..."
            
            callback_data = f"answer_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard_buttons.append([InlineKeyboardButton(text=button_text_final, callback_data=callback_data)])
            
            displayable_options.append({
                "option_id": option_id,
                "original_content": option_content, 
                "is_image_option": is_image_option_flag,
                "display_text_for_log": display_text_for_answer_log,
                "is_correct": option_data.get("is_correct", False)
            })
        
        # إضافة زر تخطي السؤال وزر إنهاء الاختبار
        skip_button = InlineKeyboardButton(text="⏭️ تخطي السؤال", callback_data=f"skip_{self.quiz_id}_{self.current_question_index}")
        end_button = InlineKeyboardButton(text="❌ إنهاء الاختبار", callback_data=f"end_{self.quiz_id}_{self.current_question_index}")
        keyboard_buttons.append([skip_button, end_button])
            
        return InlineKeyboardMarkup(keyboard_buttons), displayable_options

    def _format_time_remaining(self, seconds_remaining):
        """تنسيق الوقت المتبقي بشكل مناسب للعرض"""
        if seconds_remaining <= 0:
            return "00:00"
        
        minutes = math.floor(seconds_remaining / 60)
        seconds = math.floor(seconds_remaining % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    async def update_timer_display(self, context: CallbackContext):
        """تحديث عرض العداد في رسالة السؤال"""
        job_data = context.job.data
        chat_id = job_data["chat_id"]
        quiz_id_from_job = job_data["quiz_id"]
        q_idx = job_data["question_index"]
        msg_id = job_data["message_id"]
        is_image = job_data["is_image"]
        question_text = job_data["question_text"]
        header = job_data["header"]
        options_keyboard = job_data["options_keyboard"]  # استرجاع لوحة المفاتيح المخزنة
        
        # التحقق من أن العداد لا يزال نشطاً للسؤال الحالي
        if not self.active or quiz_id_from_job != self.quiz_id or q_idx != self.current_question_index:
            logger.debug(f"[QuizLogic {self.quiz_id}] Timer update cancelled - question changed or quiz inactive")
            return
        
        # حساب الوقت المتبقي
        elapsed_time = time.time() - self.question_start_time
        remaining_time = max(0, self.question_time_limit - elapsed_time)
        
        # تنسيق الوقت المتبقي
        time_display = self._format_time_remaining(remaining_time)
        
        # إضافة عداد الوقت إلى نص السؤال
        timer_text = f"⏱️ الوقت المتبقي: {time_display}"
        full_text = f"{header}{question_text}\n\n{timer_text}"
        
        try:
            if is_image:
                await safe_edit_message_caption(context.bot, chat_id, msg_id, caption=full_text, reply_markup=options_keyboard, parse_mode="HTML")
            else:
                await safe_edit_message_text(context.bot, chat_id, msg_id, text=full_text, reply_markup=options_keyboard, parse_mode="HTML")
                
            # جدولة التحديث التالي إذا كان لا يزال هناك وقت متبقي
            if remaining_time > 5:  # تحديث كل 5 ثوانٍ
                update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(update_job_name, context)
                context.job_queue.run_once(
                    self.update_timer_display, 
                    5.0,  # تحديث كل 5 ثوانٍ لتجنب تجاوز حدود تيليجرام
                    data=job_data,
                    name=update_job_name
                )
            elif remaining_time > 0:  # تحديث أخير قبل انتهاء الوقت
                update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(update_job_name, context)
                context.job_queue.run_once(
                    self.update_timer_display, 
                    remaining_time,
                    data=job_data,
                    name=update_job_name
                )
        except Exception as e:
            logger.warning(f"[QuizLogic {self.quiz_id}] Failed to update timer display: {e}")
    
    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None):
        if not self.active: return END 

        for msg_id in self.sent_option_image_message_ids:
            try: await bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass 
        self.sent_option_image_message_ids = []

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
            api_options = current_question_data.get("options", [])

            if len(api_options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Q {q_id_log} (idx {self.current_question_index}) has {len(api_options)} opts. Skipping.")
                q_text_skip = current_question_data.get("question_text") or "سؤال غير صالح (خيارات قليلة)"
                self.answers.append({"question_id": q_id_log, "question_text": q_text_skip, "chosen_option_id": None, "chosen_option_text": "تم تخطي السؤال (خيارات غير كافية)", "correct_option_id": None, "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True), "is_correct": False, "time_taken": -998, "status": "skipped_auto"})
                self.current_question_index += 1
                continue 
            
            options_keyboard, displayable_options_for_q = self._create_display_options_and_keyboard(api_options)
            current_question_data['_displayable_options'] = displayable_options_for_q

            option_image_counter_for_labeling = 0
            for option_detail in displayable_options_for_q:
                if option_detail["is_image_option"]:
                    try:
                        display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter_for_labeling] if option_image_counter_for_labeling < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter_for_labeling + 1}"
                        sent_opt_img_msg = await bot.send_photo(chat_id=self.chat_id, photo=option_detail["original_content"], caption=f"الخيار: {display_label}")
                        self.sent_option_image_message_ids.append(sent_opt_img_msg.message_id)
                        option_image_counter_for_labeling += 1
                        await asyncio.sleep(0.2) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option (URL: {option_detail['original_content']}), q_id {q_id_log}: {e_img_opt}")
            
            header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
            main_q_image_url = current_question_data.get("image_url")
            main_q_text_from_data = current_question_data.get("question_text") or ""
            main_q_text_from_data = str(main_q_text_from_data).strip()

            question_display_text = main_q_text_from_data
            if not main_q_text_from_data and main_q_image_url: question_display_text = "السؤال معروض في الصورة أعلاه."
            elif not main_q_text_from_data and not main_q_image_url: question_display_text = "نص السؤال غير متوفر حالياً."
            
            # إضافة عداد الوقت الأولي
            time_display = self._format_time_remaining(self.question_time_limit)
            timer_text = f"\n\n⏱️ الوقت المتبقي: {time_display}"
            full_question_text = question_display_text + timer_text
            
            sent_main_q_message = None
            try:
                if main_q_image_url:
                    sent_main_q_message = await bot.send_photo(chat_id=self.chat_id, photo=main_q_image_url, caption=header + full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                else:
                    sent_main_q_message = await bot.send_message(chat_id=self.chat_id, text=header + full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
            except Exception as e_send_q:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send Q {q_id_log} (idx {self.current_question_index}): {e_send_q}")
                self.answers.append({"question_id": q_id_log, "question_text": question_display_text, "chosen_option_id": None, "chosen_option_text": "خطأ في إرسال السؤال", "correct_option_id": None, "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True), "is_correct": False, "time_taken": -999, "status": "error_sending"})
                self.current_question_index += 1
                continue 
            
            if sent_main_q_message:
                self.last_question_message_id = sent_main_q_message.message_id
                self.question_start_time = time.time()
                
                # Set up the timer for this question
                job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(job_name, context)
                context.job_queue.run_once(
                    self.question_timeout_callback, 
                    self.question_time_limit, 
                    data={"chat_id": self.chat_id, "user_id": self.user_id, "quiz_id": self.quiz_id, "question_index_at_timeout": self.current_question_index, "main_question_message_id": self.last_question_message_id, "option_image_ids": list(self.sent_option_image_message_ids)}, name=job_name)
                logger.info(f"[QuizLogic {self.quiz_id}] Timer set for Q{self.current_question_index}, job: {job_name}")
                
                # إعداد مؤقت تحديث العداد
                update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(update_job_name, context)
                context.job_queue.run_once(
                    self.update_timer_display, 
                    5.0,  # تحديث أول بعد 5 ثوانٍ
                    data={
                        "chat_id": self.chat_id,
                        "quiz_id": self.quiz_id,
                        "question_index": self.current_question_index,
                        "message_id": self.last_question_message_id,
                        "is_image": bool(main_q_image_url),
                        "question_text": question_display_text,
                        "header": header,
                        "options_keyboard": options_keyboard  # تخزين لوحة المفاتيح لاستخدامها في التحديثات
                    },
                    name=update_job_name
                )
                
                return TAKING_QUIZ 
            else: 
                logger.error(f"[QuizLogic {self.quiz_id}] sent_main_q_message was None for q_idx {self.current_question_index}. Error in logic.")
                self.current_question_index += 1 
                if self.current_question_index >= self.total_questions: break 
                continue 
        
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed/skipped. Showing results. User {self.user_id}")
        # Use context.bot here as self.bot is not an attribute of QuizLogic
        return await self.show_results(context.bot, context, update)
        
    async def handle_skip_question(self, update: Update, context: CallbackContext, callback_data: str) -> int:
        """معالجة تخطي السؤال الحالي والانتقال للسؤال التالي"""
        if not self.active:
            return END
            
        query = update.callback_query
        await query.answer("تم تخطي السؤال")
        
        # تسجيل السؤال المتخطى في سجل الإجابات
        current_question_data = self.questions_data[self.current_question_index]
        q_id = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        q_text = current_question_data.get('question_text', 'سؤال غير متوفر')
        
        # حساب الوقت المستغرق حتى التخطي
        time_taken = time.time() - self.question_start_time if self.question_start_time else 0
        
        # إضافة معلومات السؤال المتخطى إلى سجل الإجابات
        self.answers.append({
            "question_id": q_id,
            "question_text": q_text,
            "chosen_option_id": None,
            "chosen_option_text": "تم تخطي السؤال",
            "correct_option_id": None,
            "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True),
            "is_correct": False,
            "time_taken": time_taken,
            "status": "skipped_by_user"
        })
        
        # إلغاء مؤقت السؤال الحالي
        question_timer_job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(question_timer_job_name, context)
        
        # إلغاء مؤقت تحديث العداد
        update_timer_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(update_timer_job_name, context)
        
        # تعديل رسالة السؤال لإزالة أزرار الإجابة
        if self.last_question_message_id:
            try:
                q_text_skipped = f"<s>{q_text}</s>\n<b>تم تخطي السؤال</b>"
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, self.chat_id, self.last_question_message_id, caption=q_text_skipped, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, self.last_question_message_id, text=q_text_skipped, reply_markup=None, parse_mode="HTML")
            except Exception as e_edit_skipped:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit skipped Q msg: {e_edit_skipped}")
        
        # الانتقال للسؤال التالي
        self.current_question_index += 1
        
        # التحقق مما إذا كان هناك أسئلة متبقية
        if self.current_question_index < self.total_questions:
            return await self.send_question(context.bot, context)
        else:
            return await self.show_results(context.bot, context)
    
    async def handle_end_quiz(self, update: Update, context: CallbackContext, callback_data: str) -> int:
        """معالجة إنهاء الاختبار فوراً وعرض النتائج"""
        if not self.active:
            return END
            
        query = update.callback_query
        await query.answer("تم إنهاء الاختبار")
        
        # تسجيل السؤال الحالي كمتخطى
        current_question_data = self.questions_data[self.current_question_index]
        q_id = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        q_text = current_question_data.get('question_text', 'سؤال غير متوفر')
        
        # حساب الوقت المستغرق حتى الإنهاء
        time_taken = time.time() - self.question_start_time if self.question_start_time else 0
        
        # تعديل رسالة السؤال لإزالة أزرار الإجابة
        if self.last_question_message_id:
            try:
                q_text_ended = f"<s>{q_text}</s>\n<b>تم إنهاء الاختبار</b>"
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, self.chat_id, self.last_question_message_id, caption=q_text_ended, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, self.last_question_message_id, text=q_text_ended, reply_markup=None, parse_mode="HTML")
            except Exception as e_edit_ended:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit ended Q msg: {e_edit_ended}")
        
        # إضافة معلومات السؤال الحالي إلى سجل الإجابات
        self.answers.append({
            "question_id": q_id,
            "question_text": q_text,
            "chosen_option_id": None,
            "chosen_option_text": "تم إنهاء الاختبار",
            "correct_option_id": None,
            "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True),
            "is_correct": False,
            "time_taken": time_taken,
            "status": "quiz_ended_by_user"
        })
        
        # تسجيل باقي الأسئلة كمتخطاة
        for i in range(self.current_question_index + 1, self.total_questions):
            question_data = self.questions_data[i]
            q_id = question_data.get('question_id', f'q_idx_{i}')
            q_text = question_data.get('question_text', 'سؤال غير متوفر')
            
            self.answers.append({
                "question_id": q_id,
                "question_text": q_text,
                "chosen_option_id": None,
                "chosen_option_text": "تم إنهاء الاختبار قبل الوصول لهذا السؤال",
                "correct_option_id": None,
                "correct_option_text": self._get_correct_option_display_text(question_data, for_skip=True),
                "is_correct": False,
                "time_taken": -1,
                "status": "not_reached_quiz_ended"
            })
        
        # إلغاء مؤقت السؤال الحالي
        question_timer_job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(question_timer_job_name, context)
        
        # إلغاء مؤقت تحديث العداد
        update_timer_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(update_timer_job_name, context)
        
        # عرض النتائج
        return await self.show_results(context.bot, context)
    
    async def handle_answer(self, update: Update, context: CallbackContext, callback_data: str) -> int:
        query = update.callback_query
        await query.answer()
        
        parts = callback_data.split("_")
        if len(parts) < 4: logger.warning(f"[QuizLogic {self.quiz_id}] Invalid answer callback: {callback_data}"); return TAKING_QUIZ

        ans_quiz_id, ans_q_idx_str = parts[1], parts[2]
        chosen_option_id_from_callback = "_".join(parts[3:])
        ans_q_idx = int(ans_q_idx_str)

        if not self.active or ans_quiz_id != self.quiz_id or ans_q_idx != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched answer. Active:{self.active}({self.quiz_id} vs {ans_quiz_id}), Qidx:{self.current_question_index} vs {ans_q_idx}. Ignoring.")
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time
        
        # إيقاف مؤقت انتهاء الوقت
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(job_name, context)
        
        # إيقاف مؤقت تحديث العداد
        update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(update_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        chosen_option_text_for_log = "غير محدد"
        is_correct_answer = False
        correct_option_id_for_log = None
        correct_option_text_for_log = self._get_correct_option_display_text(current_question_data)

        processed_options = current_question_data.get('_displayable_options', [])
        if not processed_options: # Fallback if _displayable_options somehow not set
            logger.error(f"[QuizLogic {self.quiz_id}] _displayable_options not found for Q {q_id_log}. This is a bug.")
            # Attempt to rebuild or use raw options, but this indicates an issue
            _, processed_options = self._create_display_options_and_keyboard(current_question_data.get("options", []))

        for option_detail in processed_options:
            if str(option_detail["option_id"]) == str(chosen_option_id_from_callback):
                chosen_option_text_for_log = option_detail["display_text_for_log"]
                is_correct_answer = option_detail["is_correct"]
                break
        
        if is_correct_answer: self.score += 1

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id_from_callback,
            "chosen_option_text": chosen_option_text_for_log,
            "correct_option_id": self._get_correct_option_id(current_question_data), # Get actual ID
            "correct_option_text": correct_option_text_for_log,
            "is_correct": is_correct_answer,
            "time_taken": round(time_taken, 2),
            "status": "answered"
        })
        
        if self.last_question_message_id:
            try:
                q_text_answered = f"<s>{current_question_data.get('question_text', '')}</s>\n<b>تمت الإجابة.</b>"
                # Use context.bot here
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, self.chat_id, self.last_question_message_id, caption=q_text_answered, parse_mode="HTML", reply_markup=None)
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, self.last_question_message_id, text=q_text_answered, parse_mode="HTML", reply_markup=None)
            except Exception as e_edit_answered:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit answered Q msg: {e_edit_answered}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            # Use context.bot here
            return await self.send_question(context.bot, context, update)
        else:
            # Use context.bot here
            return await self.show_results(context.bot, context, update)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        chat_id = job_data["chat_id"]
        user_id = job_data["user_id"]
        quiz_id_from_job = job_data["quiz_id"]
        q_idx_at_timeout = job_data["question_index_at_timeout"]
        main_q_msg_id = job_data["main_question_message_id"]
        option_img_ids_from_job = job_data.get("option_image_ids", [])

        logger.info(f"[QuizLogic {quiz_id_from_job}] Timeout for Q{q_idx_at_timeout}, user {user_id}")

        # إيقاف مؤقت تحديث العداد عند انتهاء الوقت
        update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(update_job_name, context)

        if not self.active or quiz_id_from_job != self.quiz_id or q_idx_at_timeout != self.current_question_index:
            logger.info(f"[QuizLogic {quiz_id_from_job}] Stale timeout for Q{q_idx_at_timeout}. Current Q_idx: {self.current_question_index}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": self._get_correct_option_id(current_question_data),
            "correct_option_text": self._get_correct_option_display_text(current_question_data),
            "is_correct": False,
            "time_taken": self.question_time_limit, 
            "status": "timed_out"
        })

        if main_q_msg_id:
            try:
                q_text_timeout = f"<s>{current_question_data.get('question_text', '')}</s>\n<b>انتهى الوقت!</b>"
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, chat_id, main_q_msg_id, caption=q_text_timeout, parse_mode="HTML", reply_markup=None)
                else:
                    await safe_edit_message_text(context.bot, chat_id, main_q_msg_id, text=q_text_timeout, parse_mode="HTML", reply_markup=None)
            except Exception as e_edit_timeout:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit timed-out Q msg: {e_edit_timeout}")
        
        for opt_img_id in option_img_ids_from_job:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=opt_img_id)
            except Exception: pass
        if main_q_msg_id in self.sent_option_image_message_ids: 
             self.sent_option_image_message_ids.remove(main_q_msg_id) 

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) 
        else:
            await self.show_results(context.bot, context) 

    def _get_correct_option_id(self, question_data):
        options = question_data.get("options", [])
        for opt in options:
            if opt.get("is_correct"): return opt.get("option_id")
        return None

    def _get_correct_option_display_text(self, question_data, for_skip=False):
        processed_options = question_data.get('_displayable_options')
        raw_options_api = question_data.get("options", [])
        
        target_options_list = processed_options if processed_options else raw_options_api
        key_for_text = "display_text_for_log" if processed_options else "option_text"

        for opt_detail in target_options_list:
            if opt_detail.get("is_correct"): 
                text = opt_detail.get(key_for_text, "غير متوفر")
                if processed_options and opt_detail.get("is_image_option") and not for_skip:
                    # For displayable options that are images, we already have a good label
                    return opt_detail.get("display_text_for_log", "صورة (غير محددة)")
                elif not processed_options and is_image_url(str(text)) and not for_skip:
                    # If using raw options and it's an image URL, just indicate it's an image
                    return "صورة (الإجابة الصحيحة)"
                return str(text)
        return "غير متوفر"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {self.user_id}")
        self.active = False 
        
        # Cleanup timers and any lingering question messages if not already handled
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index -1}" # Last active question
        remove_job_if_exists(job_name, context)
        if self.last_question_message_id:
            try: 
                # Attempt to remove keyboard from the very last question message if it's still there
                # This might have been done by handle_answer or timeout, but as a fallback
                current_q_data_for_edit = self.questions_data[self.current_question_index -1] if self.current_question_index > 0 else None
                if current_q_data_for_edit:
                    q_text_final = f"<s>{current_q_data_for_edit.get('question_text', '')}</s>\n<b>انتهى الاختبار.</b>"
                    if current_q_data_for_edit.get("image_url"):
                        await safe_edit_message_caption(bot, self.chat_id, self.last_question_message_id, caption=q_text_final, parse_mode="HTML", reply_markup=None)
                    else:
                        await safe_edit_message_text(bot, self.chat_id, self.last_question_message_id, text=q_text_final, parse_mode="HTML", reply_markup=None)
            except Exception: pass # Best effort
        for msg_id in self.sent_option_image_message_ids:
            try: await bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass
        self.sent_option_image_message_ids = []

        total_answered = sum(1 for ans in self.answers if ans["status"] == "answered")
        total_skipped_auto = sum(1 for ans in self.answers if ans["status"] == "skipped_auto")
        total_skipped_by_user = sum(1 for ans in self.answers if ans["status"] == "skipped_by_user")
        total_timed_out = sum(1 for ans in self.answers if ans["status"] == "timed_out")
        total_error_sending = sum(1 for ans in self.answers if ans["status"] == "error_sending")
        total_quiz_ended = sum(1 for ans in self.answers if ans["status"] in ["quiz_ended_by_user", "not_reached_quiz_ended"])
        
        total_processed_questions = len(self.answers)
        percentage = (self.score / total_processed_questions * 100) if total_processed_questions > 0 else 0
        
        total_time_taken_seconds = sum(ans["time_taken"] for ans in self.answers if ans["time_taken"] > 0) # Only positive times
        avg_time_per_q_seconds = (total_time_taken_seconds / total_answered) if total_answered > 0 else 0

        # حساب إجمالي الأسئلة المتخطاة/المهملة
        total_skipped_questions = total_skipped_auto + total_skipped_by_user + total_timed_out + total_error_sending + total_quiz_ended

        # Update DB with final results
        if self.db_manager and self.db_quiz_session_id:
            try:
                # Calculate wrong_answers and skipped_answers based on existing variables
                wrong_answers_calc = total_answered - self.score
                skipped_answers_calc = total_skipped_questions
                quiz_end_time_dt_calc = datetime.now(timezone.utc) # To match original variable name for clarity

                self.db_manager.end_quiz_session(
                    user_id=self.user_id,
                    quiz_session_uuid=self.db_quiz_session_id,
                    score=self.score,
                    wrong_answers=wrong_answers_calc,
                    skipped_answers=skipped_answers_calc,
                    score_percentage=round(percentage, 2),
                    completed_at=quiz_end_time_dt_calc,
                    time_taken_seconds=round(total_time_taken_seconds, 2),
                    answers_details_json=json.dumps(self.answers, ensure_ascii=False)
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz session {self.db_quiz_session_id} updated in DB with final results.")
            except Exception as e_db_end: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz end update: {e_db_end}", exc_info=True)
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager or session_id unavailable. Cannot log quiz end results.")

        results_text = f"🏁 <b>نتائج اختبار '{self.quiz_name}'</b> 🏁\n\n"
        results_text += f"🎯 نتيجتك: {self.score} من {total_processed_questions}\n"
        results_text += f"✅ الإجابات الصحيحة: {self.score}\n"
        results_text += f"❌ الإجابات الخاطئة: {total_answered - self.score}\n" 
        results_text += f"⏭️ الأسئلة المتخطاة/المهملة: {total_skipped_questions}\n"
        results_text += f"📊 النسبة المئوية: {percentage:.2f}%\n"
        if avg_time_per_q_seconds > 0:
            results_text += f"⏱️ متوسط وقت الإجابة للسؤال: {avg_time_per_q_seconds:.2f} ثانية\n"
        results_text += "\n📜 <b>تفاصيل الإجابات:</b>\n"

        for i, ans in enumerate(self.answers):
            q_text = ans.get('question_text')
            if q_text:
                q_text_short = q_text[:50] + ("..." if len(q_text) > 50 else "")
            else:
                q_text_short = "سؤال غير متوفر"
            results_text += f"\n<b>سؤال {i+1}:</b> \"{q_text_short}\"\n"
            if ans['status'] == 'answered':
                chosen_text_short = ans['chosen_option_text'][:50] + ("..." if len(ans['chosen_option_text']) > 50 else "")
                correct_text_short = ans['correct_option_text'][:50] + ("..." if len(ans['correct_option_text']) > 50 else "")
                results_text += f" - اخترت: {chosen_text_short} ({'صحيح ✅' if ans['is_correct'] else 'خطأ ❌'})\n"
                if not ans['is_correct']:
                    results_text += f" - الصحيح: {correct_text_short}\n"
                    
                    # إضافة شرح للإجابات الخاطئة فقط
                    question_id = ans.get('question_id')
                    if question_id:
                        # البحث عن السؤال في questions_data باستخدام question_id
                        question_data = None
                        for q in self.questions_data:
                            if str(q.get('question_id')) == str(question_id):
                                question_data = q
                                break
                        
                        if question_data:
                            # إضافة الشرح إذا كان متوفراً
                            explanation = question_data.get('explanation')
                            explanation_image = question_data.get('explanation_image_path')
                            
                            if explanation:
                                results_text += f" - <b>الشرح:</b> {explanation}\n"
                            
                            if explanation_image:
                                results_text += f" - <b>صورة توضيحية:</b> {explanation_image}\n"
            elif ans['status'] == 'timed_out':
                results_text += " - الحالة: انتهى الوقت ⌛\n"
            elif ans['status'] == 'skipped_auto':
                results_text += " - الحالة: تم التخطي (خيارات غير كافية) ⏭️\n"
            elif ans['status'] == 'skipped_by_user':
                results_text += " - الحالة: تم التخطي بواسطة المستخدم ⏭️\n"
            elif ans['status'] == 'quiz_ended_by_user':
                results_text += " - الحالة: تم إنهاء الاختبار بواسطة المستخدم ❌\n"
            elif ans['status'] == 'not_reached_quiz_ended':
                results_text += " - الحالة: لم يتم الوصول للسؤال (تم إنهاء الاختبار) ❌\n"
            elif ans['status'] == 'error_sending':
                results_text += " - الحالة: خطأ في إرسال السؤال ⚠️\n"
            else:
                results_text += f" - الحالة: {ans['status']}\n"

        # Determine the message to edit or send
        target_message_id = None
        if update and update.callback_query and update.callback_query.message:
            target_message_id = update.callback_query.message.message_id
        elif self.last_question_message_id: # Fallback to last question message ID
            target_message_id = self.last_question_message_id
        
        # Fallback if context.user_data doesn't have the specific message ID
        if not target_message_id and context and hasattr(context, 'user_data'):
            target_message_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")

        keyboard = [
            [InlineKeyboardButton("✨ ابدأ اختباراً جديداً", callback_data="quiz_action_restart_quiz_cb")],
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="menu_stats")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="quiz_action_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if target_message_id:
            try:
                await safe_edit_message_text(bot, self.chat_id, target_message_id, results_text, reply_markup, parse_mode="HTML")
            except Exception as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message for results: {e_edit_results}")
                # Fallback to sending a new message
                sent_msg = await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
                if sent_msg and context and hasattr(context, 'user_data'):
                    context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_msg.message_id
        else:
            sent_msg = await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
            if sent_msg and context and hasattr(context, 'user_data'):
                context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_msg.message_id

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed")
        return SHOWING_RESULTS

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str, preserve_current_logic_in_userdata: bool = False):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        
        # Cancel any active timers for this quiz
        for q_idx in range(self.total_questions):
            job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{q_idx}"
            remove_job_if_exists(job_name, context)
            update_job_name = f"timer_update_{self.chat_id}_{self.quiz_id}_{q_idx}"
            remove_job_if_exists(update_job_name, context)
        
        # Remove this quiz logic instance from user_data if requested
        if not preserve_current_logic_in_userdata and context and hasattr(context, 'user_data'):
            quiz_logic_key = f"quiz_logic_instance_{user_id}"
            if quiz_logic_key in context.user_data and context.user_data[quiz_logic_key] == self:
                context.user_data.pop(quiz_logic_key, None)
                logger.debug(f"[QuizLogic {self.quiz_id}] Removed self from user_data[{quiz_logic_key}]")
