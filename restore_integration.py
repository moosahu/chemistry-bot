#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
تكامل استعادة النتائج القديمة مع البوت
يضيف أوامر إدارية لاستعادة النتائج
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from config import logger, ADMIN_USER_IDS
from restore_old_quiz_results import QuizResultsRestorer

class RestoreResultsIntegration:
    """تكامل استعادة النتائج مع البوت"""
    
    def __init__(self, db_manager):
        """تهيئة التكامل"""
        self.db_manager = db_manager
        self.restorer = QuizResultsRestorer(db_manager)
        logger.info("تم تهيئة تكامل استعادة النتائج")

async def restore_analyze_command(update: Update, context: CallbackContext):
    """أمر تحليل النتائج القابلة للاستعادة"""
    user_id = update.effective_user.id
    
    # التحقق من صلاحيات المدير
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ هذا الأمر متاح للمديرين فقط")
        return
    
    try:
        # الحصول على DB_MANAGER من البوت
        db_manager = context.bot_data.get('DB_MANAGER')
        if not db_manager:
            await update.message.reply_text("❌ خطأ: قاعدة البيانات غير متاحة")
            return
        
        # إنشاء مستعيد النتائج
        restorer = QuizResultsRestorer(db_manager)
        
        await update.message.reply_text("🔍 جاري تحليل النتائج القديمة...")
        
        # تحليل النتائج
        analysis = restorer.analyze_old_results()
        
        if not analysis:
            await update.message.reply_text("❌ خطأ في تحليل النتائج")
            return
        
        # إنشاء رسالة التحليل
        message = "📊 <b>تحليل النتائج القديمة</b>\n\n"
        message += f"🔢 إجمالي النتائج الصفرية: {analysis.get('total_zero_results', 0)}\n"
        message += f"✅ قابلة للاستعادة: {analysis.get('recoverable', 0)}\n"
        message += f"❌ غير قابلة للاستعادة: {analysis.get('not_recoverable', 0)}\n\n"
        
        # عرض عينة من البيانات
        sample_data = analysis.get('sample_data', [])
        if sample_data:
            message += "📋 <b>عينة من البيانات القابلة للاستعادة:</b>\n"
            for i, sample in enumerate(sample_data[:3], 1):
                message += f"{i}. المستخدم {sample['user_id']}: "
                message += f"{sample['answers_count']}/{sample['total_questions']} إجابة\n"
        
        # إضافة أزرار للإجراءات
        keyboard = []
        if analysis.get('recoverable', 0) > 0:
            keyboard.append([
                InlineKeyboardButton("🔧 استعادة جميع النتائج", callback_data="restore_all_results")
            ])
        
        keyboard.append([
            InlineKeyboardButton("🔄 تحديث التحليل", callback_data="restore_analyze")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message, 
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"خطأ في أمر تحليل الاستعادة: {e}")
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def restore_all_callback(update: Update, context: CallbackContext):
    """معالج استعادة جميع النتائج"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # التحقق من صلاحيات المدير
    if user_id not in ADMIN_USER_IDS:
        await query.edit_message_text("❌ هذا الإجراء متاح للمديرين فقط")
        return
    
    try:
        # الحصول على DB_MANAGER من البوت
        db_manager = context.bot_data.get('DB_MANAGER')
        if not db_manager:
            await query.edit_message_text("❌ خطأ: قاعدة البيانات غير متاحة")
            return
        
        # إنشاء مستعيد النتائج
        restorer = QuizResultsRestorer(db_manager)
        
        await query.edit_message_text("🔧 جاري إنشاء نسخة احتياطية...")
        
        # إنشاء نسخة احتياطية
        backup_success = restorer.create_backup_before_restore()
        if not backup_success:
            await query.edit_message_text("❌ فشل في إنشاء النسخة الاحتياطية")
            return
        
        await query.edit_message_text("🔄 جاري استعادة النتائج... قد يستغرق بعض الوقت...")
        
        # استعادة النتائج
        results = restorer.restore_all_recoverable_results()
        
        # إنشاء رسالة النتائج
        message = "✅ <b>انتهت عملية الاستعادة</b>\n\n"
        message += f"📊 إجمالي النتائج المعالجة: {results.get('total', 0)}\n"
        message += f"✅ تم استعادتها بنجاح: {results.get('restored', 0)}\n"
        message += f"❌ فشلت في الاستعادة: {results.get('failed', 0)}\n\n"
        
        if results.get('restored', 0) > 0:
            message += "🎉 تم استعادة النتائج بنجاح!\n"
            message += "يمكنك الآن تجربة التقارير لرؤية البيانات المحدثة."
        
        # إضافة زر للعودة
        keyboard = [[
            InlineKeyboardButton("📊 تحليل جديد", callback_data="restore_analyze")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message, 
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"خطأ في استعادة النتائج: {e}")
        await query.edit_message_text(f"❌ خطأ في الاستعادة: {str(e)}")

async def restore_analyze_callback(update: Update, context: CallbackContext):
    """معالج إعادة تحليل النتائج"""
    query = update.callback_query
    await query.answer()
    
    # تحويل إلى أمر تحليل عادي
    # إنشاء update مؤقت للرسالة
    temp_update = Update(
        update_id=update.update_id,
        message=query.message
    )
    
    await restore_analyze_command(temp_update, context)

# إضافة الأوامر للبوت
def add_restore_commands(application):
    """إضافة أوامر الاستعادة للبوت"""
    from telegram.ext import CommandHandler, CallbackQueryHandler
    
    # أوامر الاستعادة
    application.add_handler(CommandHandler("restore_analyze", restore_analyze_command))
    
    # معالجات الأزرار
    application.add_handler(CallbackQueryHandler(restore_all_callback, pattern="^restore_all_results$"))
    application.add_handler(CallbackQueryHandler(restore_analyze_callback, pattern="^restore_analyze$"))
    
    logger.info("تم إضافة أوامر استعادة النتائج للبوت")

# تعليمات الاستخدام
RESTORE_USAGE_INSTRUCTIONS = """
🔧 **أوامر استعادة النتائج القديمة:**

📊 `/restore_analyze` - تحليل النتائج القابلة للاستعادة

**ملاحظات مهمة:**
- ✅ يتم إنشاء نسخة احتياطية تلقائياً
- ✅ يعيد حساب النتائج من تفاصيل الإجابات المحفوظة
- ⚠️ النتائج التي لا تحتوي على تفاصيل إجابات لا يمكن استعادتها
- 🔒 متاح للمديرين فقط
"""

