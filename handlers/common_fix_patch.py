#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف تصحيح لمشكلة UnboundLocalError في دالة main_menu_callback في ملف common.py
"""

import sys
import os
import re

def patch_common_py():
    """
    تطبيق التعديلات على ملف common.py
    """
    # تحديد مسار ملف common.py
    common_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "common.py")
    
    if not os.path.exists(common_path):
        # البحث في مجلد handlers
        handlers_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handlers")
        if os.path.exists(handlers_dir):
            common_path = os.path.join(handlers_dir, "common.py")
            if not os.path.exists(common_path):
                print(f"خطأ: ملف common.py غير موجود في {os.path.dirname(os.path.abspath(__file__))} أو {handlers_dir}")
                return False
    
    # قراءة محتوى الملف
    with open(common_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # إنشاء نسخة احتياطية من الملف
    backup_path = common_path + ".bak2"
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"تم إنشاء نسخة احتياطية من الملف في {backup_path}")
    
    # تعديل دالة main_menu_callback لإصلاح خطأ UnboundLocalError
    main_menu_pattern = r"async def main_menu_callback\(update: Update, context: CallbackContext\).*?return state_to_return"
    main_menu_match = re.search(main_menu_pattern, content, re.DOTALL)
    if main_menu_match:
        main_menu_text = main_menu_match.group(0)
        
        # تعديل بداية الدالة لتعريف المتغير data بشكل آمن
        new_main_menu_text = main_menu_text.replace(
            "async def main_menu_callback(update: Update, context: CallbackContext) -> int:",
            """async def main_menu_callback(update: Update, context: CallbackContext) -> int:
    # تعريف المتغير data بشكل افتراضي لتجنب UnboundLocalError
    data = "main_menu"  # قيمة افتراضية"""
        )
        
        # تعديل منطق استخراج البيانات من callback_query
        new_main_menu_text = new_main_menu_text.replace(
            "if query:",
            """if query:
        # استخراج البيانات من callback_query
        data = query.data"""
        )
        
        content = content.replace(main_menu_text, new_main_menu_text)
        print("تم تعديل دالة main_menu_callback لإصلاح خطأ UnboundLocalError")
    
    # كتابة المحتوى المعدل إلى الملف
    with open(common_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"تم تطبيق التعديلات على ملف {common_path}")
    return True

def main():
    """
    الدالة الرئيسية لتطبيق التعديلات
    """
    print("بدء تطبيق التعديلات على ملف common.py...")
    
    # تطبيق التعديلات على ملف common.py
    success = patch_common_py()
    
    if success:
        print("\nتم تطبيق التعديلات بنجاح!")
        print("يرجى إعادة تشغيل البوت لتفعيل التعديلات.")
    else:
        print("\nحدث خطأ أثناء تطبيق التعديلات.")
        print("يرجى التحقق من وجود الملف في المسار الصحيح.")

if __name__ == "__main__":
    main()
