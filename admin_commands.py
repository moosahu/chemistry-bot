#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أوامر إدارية للتحكم في حظر المستخدمين
يتيح للمدير حظر وإلغاء حظر المستخدمين وإدارة النظام
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters
)

# إعداد التسجيل
logger = logging.getLogger(__name__)

# حالات المحادثة
ADMIN_MAIN_MENU = 100
BLOCK_USER_INPUT = 101
UNBLOCK_USER_INPUT = 102
BLOCK_REASON_INPUT = 103

def create_admin_menu_keyboard():
    """إنشاء لوحة مفاتيح القائمة الإدارية"""
    keyboard = [
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_block_user")],
        [InlineKeyboardButton("✅ إلغاء حظر مستخدم", callback_data="admin_unblock_user")],
        [InlineKeyboardButton("📋 قائمة المحظورين", callback_data="admin_blocked_list")],
        [InlineKeyboardButton("📊 إحصائيات النظام", callback_data="admin_system_stats")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel_command(update: Update, context: CallbackContext) -> int:
    """أمر فتح لوحة التحكم الإدارية"""
    from admin_security_system import get_admin_security_manager
    
    security_manager = get_admin_security_manager()
    if not security_manager:
        await update.message.reply_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    
    if not security_manager.is_admin(user_id):
        await update.message.reply_text("👑 هذا الأمر متاح للمدراء فقط.")
        return ConversationHandler.END
    
    admin_text = """
👑 **لوحة التحكم الإدارية**

مرحباً أيها المدير! يمكنك استخدام الأزرار أدناه لإدارة النظام:

🚫 **حظر مستخدم**: منع مستخدم من استخدام البوت
✅ **إلغاء حظر**: السماح لمستخدم محظور بالعودة
📋 **قائمة المحظورين**: عرض جميع المستخدمين المحظورين
📊 **إحصائيات النظام**: عرض معلومات النظام
"""
    
    keyboard = create_admin_menu_keyboard()
    
    await update.message.reply_text(
        text=admin_text,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    
    return ADMIN_MAIN_MENU

async def admin_menu_callback(update: Update, context: CallbackContext) -> int:
    """معالج أزرار القائمة الإدارية"""
    query = update.callback_query
    await query.answer()
    
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager or not security_manager.is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح لك بالوصول.")
        return ConversationHandler.END
    
    if query.data == "admin_block_user":
        await query.edit_message_text(
            "🚫 **حظر مستخدم**\n\n"
            "أرسل معرف المستخدم (User ID) الذي تريد حظره:\n"
            "مثال: `123456789`\n\n"
            "يمكنك الحصول على معرف المستخدم من خلال إعادة توجيه رسالة منه أو استخدام بوت @userinfobot",
            parse_mode='Markdown'
        )
        return BLOCK_USER_INPUT
    
    elif query.data == "admin_unblock_user":
        await query.edit_message_text(
            "✅ **إلغاء حظر مستخدم**\n\n"
            "أرسل معرف المستخدم (User ID) الذي تريد إلغاء حظره:\n"
            "مثال: `123456789`",
            parse_mode='Markdown'
        )
        return UNBLOCK_USER_INPUT
    
    elif query.data == "admin_blocked_list":
        return await show_blocked_users_list(update, context)
    
    elif query.data == "admin_system_stats":
        return await show_system_stats(update, context)
    
    elif query.data == "main_menu":
        try:
            from handlers.common import main_menu_callback
            await main_menu_callback(update, context)
        except ImportError:
            await query.edit_message_text("تم العودة للقائمة الرئيسية.")
        return ConversationHandler.END
    
    return ADMIN_MAIN_MENU

async def handle_block_user_input(update: Update, context: CallbackContext) -> int:
    """معالج إدخال معرف المستخدم للحظر"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager:
        await update.message.reply_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    try:
        user_id_to_block = int(update.message.text.strip())
        
        # التحقق من أن المستخدم ليس مدير
        if security_manager.is_admin(user_id_to_block):
            await update.message.reply_text("❌ لا يمكن حظر مدير!")
            return ADMIN_MAIN_MENU
        
        # حفظ معرف المستخدم المراد حظره
        context.user_data['user_to_block'] = user_id_to_block
        
        await update.message.reply_text(
            f"🚫 **تأكيد الحظر**\n\n"
            f"هل أنت متأكد من حظر المستخدم `{user_id_to_block}`؟\n\n"
            f"أرسل سبب الحظر أو اكتب 'تأكيد' للمتابعة بدون سبب:",
            parse_mode='Markdown'
        )
        
        return BLOCK_REASON_INPUT
        
    except ValueError:
        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح!\n"
            "يجب أن يكون رقماً صحيحاً مثل: 123456789"
        )
        return BLOCK_USER_INPUT

async def handle_block_reason_input(update: Update, context: CallbackContext) -> int:
    """معالج إدخال سبب الحظر"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager:
        await update.message.reply_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    user_to_block = context.user_data.get('user_to_block')
    if not user_to_block:
        await update.message.reply_text("❌ حدث خطأ. يرجى المحاولة مرة أخرى.")
        return ConversationHandler.END
    
    reason = update.message.text.strip()
    if reason.lower() == 'تأكيد':
        reason = "غير محدد"
    
    admin_id = update.effective_user.id
    
    # تنفيذ الحظر
    if security_manager.block_user(user_to_block, admin_id, reason):
        success_text = f"""
✅ **تم حظر المستخدم بنجاح**

👤 **معرف المستخدم**: `{user_to_block}`
👑 **تم الحظر بواسطة**: {update.effective_user.first_name}
📝 **السبب**: {reason}
⏰ **التاريخ**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
        
        # إرسال رسالة النجاح مع زر العودة
        keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            success_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # محاولة إشعار المستخدم المحظور (اختياري)
        try:
            await context.bot.send_message(
                chat_id=user_to_block,
                text=f"🚫 تم حظرك من استخدام هذا البوت.\n\nالسبب: {reason}\n\nإذا كنت تعتقد أن هذا خطأ، تواصل مع الإدارة."
            )
        except Exception as e:
            logger.info(f"لم يتم إرسال إشعار الحظر للمستخدم {user_to_block}: {e}")
        
        # مسح بيانات المستخدم المؤقتة
        context.user_data.pop('user_to_block', None)
        
    else:
        await update.message.reply_text(
            f"⚠️ المستخدم `{user_to_block}` محظور بالفعل.",
            parse_mode='Markdown'
        )
        context.user_data.pop('user_to_block', None)
    
    return ADMIN_MAIN_MENU

async def handle_unblock_user_input(update: Update, context: CallbackContext) -> int:
    """معالج إدخال معرف المستخدم لإلغاء الحظر"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager:
        await update.message.reply_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    try:
        user_id_to_unblock = int(update.message.text.strip())
        admin_id = update.effective_user.id
        
        # تنفيذ إلغاء الحظر
        if security_manager.unblock_user(user_id_to_unblock, admin_id):
            success_text = f"""
✅ **تم إلغاء حظر المستخدم بنجاح**

👤 **معرف المستخدم**: `{user_id_to_unblock}`
👑 **تم إلغاء الحظر بواسطة**: {update.effective_user.first_name}
⏰ **التاريخ**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
            
            keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_admin_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                success_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # محاولة إشعار المستخدم بإلغاء الحظر (اختياري)
            try:
                await context.bot.send_message(
                    chat_id=user_id_to_unblock,
                    text="✅ تم إلغاء حظرك من البوت. يمكنك الآن استخدامه بشكل طبيعي."
                )
            except Exception as e:
                logger.info(f"لم يتم إرسال إشعار إلغاء الحظر للمستخدم {user_id_to_unblock}: {e}")
            
        else:
            await update.message.reply_text(
                f"⚠️ المستخدم `{user_id_to_unblock}` غير محظور.",
                parse_mode='Markdown'
            )
        
    except ValueError:
        await update.message.reply_text(
            "❌ معرف المستخدم غير صحيح!\n"
            "يجب أن يكون رقماً صحيحاً مثل: 123456789"
        )
        return UNBLOCK_USER_INPUT
    
    return ADMIN_MAIN_MENU

async def show_blocked_users_list(update: Update, context: CallbackContext) -> int:
    """عرض قائمة المستخدمين المحظورين"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager:
        await update.callback_query.edit_message_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    blocked_users = security_manager.get_blocked_users_list()
    
    if not blocked_users:
        text = "📋 **قائمة المستخدمين المحظورين**\n\n✅ لا يوجد مستخدمون محظورون حالياً."
    else:
        text = f"📋 **قائمة المستخدمين المحظورين** ({len(blocked_users)} مستخدم)\n\n"
        
        for i, user_info in enumerate(blocked_users[:10], 1):  # عرض أول 10 فقط
            user_id = user_info['user_id']
            reason = user_info['reason']
            blocked_at = user_info.get('blocked_at', 'غير محدد')
            
            # تنسيق التاريخ
            try:
                if blocked_at != 'غير محدد':
                    date_obj = datetime.fromisoformat(blocked_at.replace('Z', '+00:00'))
                    blocked_at = date_obj.strftime('%Y-%m-%d %H:%M')
            except:
                blocked_at = 'غير محدد'
            
            text += f"{i}. 👤 `{user_id}`\n"
            text += f"   📝 السبب: {reason}\n"
            text += f"   📅 التاريخ: {blocked_at}\n\n"
        
        if len(blocked_users) > 10:
            text += f"... و {len(blocked_users) - 10} مستخدم آخر"
    
    keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return ADMIN_MAIN_MENU

async def show_system_stats(update: Update, context: CallbackContext) -> int:
    """عرض إحصائيات النظام"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager:
        await update.callback_query.edit_message_text("❌ نظام الحماية غير مفعل.")
        return ConversationHandler.END
    
    # إحصائيات الحظر
    blocked_count = len(security_manager.blocked_users)
    admin_count = len(security_manager.admin_ids)
    
    # محاولة الحصول على إحصائيات المستخدمين المسجلين
    registered_count = "غير متاح"
    try:
        db_manager = context.bot_data.get("DB_MANAGER")
        if db_manager:
            # يمكن إضافة استعلام لحساب المستخدمين المسجلين
            pass
    except:
        pass
    
    stats_text = f"""
📊 **إحصائيات النظام**

👥 **المستخدمون**:
   • المسجلون: {registered_count}
   • المحظورون: {blocked_count}

👑 **الإدارة**:
   • عدد المدراء: {admin_count}

🛡️ **الحماية**:
   • نظام الحماية: ✅ مفعل
   • التحقق من التسجيل: ✅ مفعل
   • الحظر اليدوي: ✅ مفعل

⏰ **آخر تحديث**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        stats_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return ADMIN_MAIN_MENU

async def back_to_admin_menu_callback(update: Update, context: CallbackContext) -> int:
    """العودة للوحة التحكم الإدارية"""
    query = update.callback_query
    await query.answer()
    
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager or not security_manager.is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح لك بالوصول.")
        return ConversationHandler.END
    
    admin_text = """
👑 **لوحة التحكم الإدارية**

مرحباً أيها المدير! يمكنك استخدام الأزرار أدناه لإدارة النظام:

🚫 **حظر مستخدم**: منع مستخدم من استخدام البوت
✅ **إلغاء حظر**: السماح لمستخدم محظور بالعودة
📋 **قائمة المحظورين**: عرض جميع المستخدمين المحظورين
📊 **إحصائيات النظام**: عرض معلومات النظام
"""
    
    keyboard = create_admin_menu_keyboard()
    
    await query.edit_message_text(
        text=admin_text,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    
    return ADMIN_MAIN_MENU

async def cancel_admin_operation(update: Update, context: CallbackContext) -> int:
    """إلغاء العملية الإدارية"""
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

# تعريف معالج المحادثة الإدارية
admin_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("admin", admin_panel_command),
        CommandHandler("adminpanel", admin_panel_command)
    ],
    states={
        ADMIN_MAIN_MENU: [
            CallbackQueryHandler(admin_menu_callback, pattern="^(admin_|main_menu)"),
            CallbackQueryHandler(back_to_admin_menu_callback, pattern="^back_to_admin_menu$"),
        ],
        BLOCK_USER_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_block_user_input)
        ],
        UNBLOCK_USER_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unblock_user_input)
        ],
        BLOCK_REASON_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_block_reason_input)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_admin_operation),
        CallbackQueryHandler(back_to_admin_menu_callback, pattern="^back_to_admin_menu$")
    ],
    persistent=False,
    name="admin_conversation"
)

# أوامر إدارية سريعة (بدون محادثة)
async def quick_block_command(update: Update, context: CallbackContext):
    """أمر حظر سريع: /block [user_id] [reason]"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager or not security_manager.is_admin(update.effective_user.id):
        await update.message.reply_text("👑 هذا الأمر متاح للمدراء فقط.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "الاستخدام: `/block [معرف_المستخدم] [السبب]`\n"
            "مثال: `/block 123456789 مخالفة القوانين`",
            parse_mode='Markdown'
        )
        return
    
    try:
        user_id_to_block = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "غير محدد"
        
        if security_manager.is_admin(user_id_to_block):
            await update.message.reply_text("❌ لا يمكن حظر مدير!")
            return
        
        admin_id = update.effective_user.id
        
        if security_manager.block_user(user_id_to_block, admin_id, reason):
            await update.message.reply_text(
                f"✅ تم حظر المستخدم `{user_id_to_block}` بنجاح.\n"
                f"السبب: {reason}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"⚠️ المستخدم `{user_id_to_block}` محظور بالفعل.")
            
    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم غير صحيح!")

async def quick_unblock_command(update: Update, context: CallbackContext):
    """أمر إلغاء حظر سريع: /unblock [user_id]"""
    from admin_security_system import get_admin_security_manager
    security_manager = get_admin_security_manager()
    
    if not security_manager or not security_manager.is_admin(update.effective_user.id):
        await update.message.reply_text("👑 هذا الأمر متاح للمدراء فقط.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "الاستخدام: `/unblock [معرف_المستخدم]`\n"
            "مثال: `/unblock 123456789`",
            parse_mode='Markdown'
        )
        return
    
    try:
        user_id_to_unblock = int(args[0])
        admin_id = update.effective_user.id
        
        if security_manager.unblock_user(user_id_to_unblock, admin_id):
            await update.message.reply_text(
                f"✅ تم إلغاء حظر المستخدم `{user_id_to_unblock}` بنجاح.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"⚠️ المستخدم `{user_id_to_unblock}` غير محظور.")
            
    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم غير صحيح!")

# تصدير المعالجات
__all__ = [
    'admin_conversation_handler',
    'quick_block_command',
    'quick_unblock_command',
    'admin_panel_command'
]

