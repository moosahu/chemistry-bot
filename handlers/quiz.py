# DEBUG: handlers/quiz.py V15 started loading (imports first!)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
)
from telegram.constants import ParseMode

import logging
import random
from .quiz_logic import QuizLogic
from config.db_manager import get_db_connection, get_user_id # Corrected import
from utils.helpers import main_menu_keyboard # Assuming helpers.py is in utils

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Stages for conversation handler
SELECTING_ANSWER, TYPING_ANSWER = range(2)

# Initialize QuizLogic
quiz_logic = QuizLogic()

async def start_quiz(update: Update, context: CallbackContext) -> int:
    user_id = get_user_id(update)
    logger.info(f"User {user_id} started a new quiz.")
    context.user_data['current_question_index'] = 0
    context.user_data['score'] = 0
    context.user_data['quiz_questions'] = await quiz_logic.get_random_questions(user_id, 10) # Fetch 10 questions

    if not context.user_data['quiz_questions']:
        await update.message.reply_text(
            "عذراً، لا توجد أسئلة متاحة حالياً لبدء الاختبار. يرجى المحاولة لاحقاً.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    await ask_question(update, context)
    return SELECTING_ANSWER

async def ask_question(update: Update, context: CallbackContext):
    user_id = get_user_id(update)
    current_question_index = context.user_data['current_question_index']
    quiz_questions = context.user_data['quiz_questions']

    if current_question_index < len(quiz_questions):
        question_data = quiz_questions[current_question_index]
        context.user_data['current_question_id'] = question_data['id']
        context.user_data['correct_answer'] = question_data['correct_answer']
        
        question_text = f"السؤال {current_question_index + 1} من {len(quiz_questions)}:\n\n{question_data['question_text']}"
        
        options = [question_data['option1'], question_data['option2'], question_data['option3'], question_data['option4']]
        random.shuffle(options) # Randomize options
        
        keyboard = [
            [InlineKeyboardButton(options[0], callback_data=options[0])],
            [InlineKeyboardButton(options[1], callback_data=options[1])],
            [InlineKeyboardButton(options[2], callback_data=options[2])],
            [InlineKeyboardButton(options[3], callback_data=options[3])],
            [InlineKeyboardButton("إنهاء الاختبار", callback_data='stop_quiz')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query: # If called from a button press
            await update.callback_query.edit_message_text(text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif update.message: # If called from /startquiz command
            await update.message.reply_text(text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            # Fallback or error, though one of the above should always be true
            logger.warning("ask_question called without a message or callback_query update.")
            # Attempt to send to the chat ID if available
            chat_id = context.user_data.get('chat_id', user_id) # Try to get chat_id stored earlier or use user_id
            if chat_id:
                 await context.bot.send_message(chat_id=chat_id, text=question_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                logger.error(f"Could not determine chat_id to send question for user {user_id}")

    else:
        await end_quiz(update, context)

async def handle_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user_answer = query.data
    user_id = get_user_id(update)

    if user_answer == 'stop_quiz':
        await query.edit_message_text(text="تم إنهاء الاختبار بناءً على طلبك.")
        await quiz_logic.save_quiz_result(user_id, context.user_data['score'], len(context.user_data['quiz_questions']))
        logger.info(f"User {user_id} stopped the quiz. Score: {context.user_data['score']}/{len(context.user_data['quiz_questions'])}")
        await context.bot.send_message(chat_id=query.message.chat_id, text="يمكنك البدء من جديد باختيار /startquiz من القائمة.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    correct_answer = context.user_data['correct_answer']
    question_id = context.user_data['current_question_id']

    if user_answer == correct_answer:
        context.user_data['score'] += 1
        await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {user_answer} (صحيحة ✅)")
        logger.info(f"User {user_id} answered correctly for question {question_id}. Current score: {context.user_data['score']}")
    else:
        await query.edit_message_text(text=f"{query.message.text}\n\nإجابتك: {user_answer} (خاطئة ❌)\nالإجابة الصحيحة: {correct_answer}")
        logger.info(f"User {user_id} answered incorrectly for question {question_id}. Correct answer was {correct_answer}. Current score: {context.user_data['score']}")

    context.user_data['current_question_index'] += 1
    
    # Wait a bit before showing the next question or ending the quiz
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action='typing')
    # Using a job to delay the next question to allow user to read the feedback
    context.job_queue.run_once(lambda ctx: ask_question_job(ctx, query.message.chat_id), 2) # 2 seconds delay
    
    return SELECTING_ANSWER # Stay in the same state to receive next question or end

async def ask_question_job(context: CallbackContext, chat_id: int):
    # We need to reconstruct a pseudo-Update object or pass necessary info directly
    # For simplicity, we'll pass chat_id and rely on context.user_data
    # A more robust way would be to pass user_id and fetch chat_id if necessary
    # Create a simple Update-like object for ask_question to use context.bot.send_message
    class MinimalUpdate:
        def __init__(self, chat_id):
            self.message = MinimalMessage(chat_id)
            self.callback_query = None # Important for ask_question logic

    class MinimalMessage:
        def __init__(self, chat_id):
            self.chat_id = chat_id
            self.from_user = context.user_data.get('_user_reference') # if you stored user earlier

    # Try to get user_id from context if available, otherwise this might be an issue
    # This part is tricky as the original update object is not available directly in job_queue
    # We assume user_data is correctly populated for the current user of this job.
    
    # Create a mock update object. The ask_question function needs to be robust enough
    # or we pass chat_id directly to a modified ask_question_from_job
    # For now, let's assume ask_question can handle a message-less update if chat_id is available in context
    # Storing chat_id in user_data from the initial command or callback is crucial here.
    context.user_data['chat_id'] = chat_id # Ensure chat_id is available
    await ask_question(MinimalUpdate(chat_id), context)

async def end_quiz(update: Update, context: CallbackContext):
    user_id = get_user_id(update)
    score = context.user_data['score']
    total_questions = len(context.user_data['quiz_questions'])
    
    final_message = f"انتهى الاختبار!\n\nنتيجتك: {score} من {total_questions}"
    logger.info(f"User {user_id} finished the quiz. Score: {score}/{total_questions}")
    await quiz_logic.save_quiz_result(user_id, score, total_questions)
    
    # Determine if update is from callback_query or message
    if update.callback_query:
        await update.callback_query.edit_message_text(text=final_message)
        await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text="يمكنك البدء من جديد باختيار /startquiz من القائمة.", reply_markup=main_menu_keyboard())
    elif update.message: # Should not happen if quiz ends naturally after last question via button
        await update.message.reply_text(text=final_message, reply_markup=main_menu_keyboard())
    else: # Fallback, try to send to stored chat_id
        chat_id = context.user_data.get('chat_id', user_id)
        await context.bot.send_message(chat_id=chat_id, text=final_message)
        await context.bot.send_message(chat_id=chat_id, text="يمكنك البدء من جديد باختيار /startquiz من القائمة.", reply_markup=main_menu_keyboard())

    return ConversationHandler.END

async def handle_text_during_quiz(update: Update, context: CallbackContext) -> int:
    user_id = get_user_id(update)
    logger.info(f"User {user_id} sent text during quiz: {update.message.text}")
    await update.message.reply_text(
        "أنت حالياً في وضع الاختبار. يرجى استخدام الأزرار للإجابة على الأسئلة أو إنهاء الاختبار.",
        reply_markup=update.message.reply_markup # Keep the current question's keyboard if possible
    )
    return SELECTING_ANSWER # Stay in the current state

async def stop_quiz_command(update: Update, context: CallbackContext) -> int:
    user_id = get_user_id(update)
    logger.info(f"User {user_id} used /stopquiz command.")
    
    # Check if user is actually in a quiz by looking for quiz-specific user_data
    if 'quiz_questions' not in context.user_data or 'current_question_index' not in context.user_data:
        await update.message.reply_text(
            "أنت لست في اختبار حالياً. يمكنك بدء اختبار جديد باستخدام الأمر /startquiz.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    score = context.user_data.get('score', 0)
    total_questions = len(context.user_data.get('quiz_questions', []))
    
    await quiz_logic.save_quiz_result(user_id, score, total_questions)
    await update.message.reply_text(
        f"تم إنهاء الاختبار بناءً على طلبك. نتيجتك حتى الآن: {score} من {context.user_data['current_question_index']}.",
        reply_markup=main_menu_keyboard()
    )
    # Clean up user_data related to quiz
    keys_to_delete = ['current_question_index', 'score', 'quiz_questions', 'current_question_id', 'correct_answer']
    for key in keys_to_delete:
        if key in context.user_data:
            del context.user_data[key]
            
    return ConversationHandler.END

# Conversation handler for the quiz
quiz_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('startquiz', start_quiz)],
    states={
        SELECTING_ANSWER: [
            CallbackQueryHandler(handle_answer),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_during_quiz)
        ],
        # TYPING_ANSWER might not be needed if all answers are via buttons
    },
    fallbacks=[CommandHandler('stopquiz', stop_quiz_command)],
    persistent=True,  # Enable persistence
    name="quiz_conversation" # Name for persistence
)

logger.info("handlers/quiz.py V15 loaded successfully with quiz_conv_handler.")

