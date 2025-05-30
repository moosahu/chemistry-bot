#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
أداة تحليل ملف إكسل المستخدمين للتحقق من دقة البيانات وأمانها
"""

import os
import sys
import logging
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# تكوين التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def analyze_excel_file(excel_path):
    """
    تحليل ملف إكسل المستخدمين للتحقق من دقة البيانات وأمانها
    
    المعلمات:
        excel_path (str): مسار ملف الإكسل
    
    العائد:
        dict: نتائج التحليل
    """
    try:
        if not os.path.exists(excel_path):
            logger.error(f"ملف الإكسل غير موجود: {excel_path}")
            return None
        
        # قراءة ملف الإكسل
        logger.info(f"قراءة ملف الإكسل: {excel_path}")
        df = pd.read_excel(excel_path)
        
        # تحليل البيانات
        analysis_results = {
            "file_path": excel_path,
            "file_size_kb": os.path.getsize(excel_path) / 1024,
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "columns": list(df.columns),
            "data_types": {col: str(df[col].dtype) for col in df.columns},
            "null_counts": {col: df[col].isnull().sum() for col in df.columns},
            "grade_distribution": df['الصف الدراسي'].value_counts().to_dict() if 'الصف الدراسي' in df.columns else {},
            "admin_count": (df['مدير'] == 'نعم').sum() if 'مدير' in df.columns else 0,
            "sensitive_columns_check": []
        }
        
        # التحقق من وجود أعمدة حساسة غير مرغوبة
        sensitive_columns = [
            "كلمة المرور", "رمز التحقق", "رمز الدخول", "token", "password", "secret"
        ]
        
        for col in sensitive_columns:
            if any(col.lower() in c.lower() for c in df.columns):
                analysis_results["sensitive_columns_check"].append(
                    f"⚠️ تحذير: تم العثور على عمود حساس محتمل: {col}"
                )
        
        if not analysis_results["sensitive_columns_check"]:
            analysis_results["sensitive_columns_check"].append(
                "✅ لم يتم العثور على أعمدة حساسة غير مرغوبة"
            )
        
        # إنشاء مخطط توزيع الصفوف الدراسية
        if 'الصف الدراسي' in df.columns and not df['الصف الدراسي'].isnull().all():
            plt.figure(figsize=(10, 6))
            df['الصف الدراسي'].value_counts().plot(kind='bar')
            plt.title('توزيع المستخدمين حسب الصف الدراسي')
            plt.xlabel('الصف الدراسي')
            plt.ylabel('عدد المستخدمين')
            plt.tight_layout()
            
            # حفظ المخطط
            chart_dir = os.path.dirname(excel_path)
            chart_path = os.path.join(chart_dir, 'grade_distribution_chart.png')
            plt.savefig(chart_path)
            plt.close()
            
            analysis_results["grade_chart_path"] = chart_path
        
        return analysis_results
    
    except Exception as e:
        logger.error(f"خطأ أثناء تحليل ملف الإكسل: {e}")
        return None

def generate_analysis_report(analysis_results):
    """
    إنشاء تقرير تحليل ملف الإكسل
    
    المعلمات:
        analysis_results (dict): نتائج التحليل
    
    العائد:
        str: مسار ملف التقرير
    """
    try:
        if not analysis_results:
            logger.error("لا توجد نتائج تحليل لإنشاء التقرير")
            return None
        
        # إنشاء محتوى التقرير
        report_content = f"""# تقرير تحليل ملف إكسل بيانات المستخدمين

## معلومات الملف
- **اسم الملف**: {os.path.basename(analysis_results['file_path'])}
- **حجم الملف**: {analysis_results['file_size_kb']:.2f} كيلوبايت
- **عدد الصفوف**: {analysis_results['total_rows']}
- **عدد الأعمدة**: {analysis_results['total_columns']}

## الأعمدة الموجودة
{', '.join(analysis_results['columns'])}

## فحص الأمان
{chr(10).join(analysis_results['sensitive_columns_check'])}

## توزيع الصفوف الدراسية
"""
        
        # إضافة توزيع الصفوف الدراسية
        for grade, count in analysis_results['grade_distribution'].items():
            report_content += f"- **{grade}**: {count} مستخدم\n"
        
        # إضافة معلومات المدراء
        report_content += f"\n## المدراء\n- **عدد المدراء**: {analysis_results['admin_count']}\n"
        
        # إضافة معلومات القيم الفارغة
        report_content += "\n## القيم الفارغة في كل عمود\n"
        for col, null_count in analysis_results['null_counts'].items():
            report_content += f"- **{col}**: {null_count} قيمة فارغة\n"
        
        # حفظ التقرير
        report_dir = os.path.dirname(analysis_results['file_path'])
        report_filename = f"excel_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = os.path.join(report_dir, report_filename)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        logger.info(f"تم إنشاء تقرير التحليل بنجاح: {report_path}")
        return report_path
    
    except Exception as e:
        logger.error(f"خطأ أثناء إنشاء تقرير التحليل: {e}")
        return None

def main():
    """الدالة الرئيسية"""
    try:
        # البحث عن أحدث ملف إكسل في مجلد التصدير
        export_dir = '/home/ubuntu/upload/admin_tools/exports'
        if not os.path.exists(export_dir):
            logger.error(f"مجلد التصدير غير موجود: {export_dir}")
            return
        
        excel_files = [f for f in os.listdir(export_dir) if f.endswith('.xlsx')]
        if not excel_files:
            logger.error("لم يتم العثور على ملفات إكسل في مجلد التصدير")
            return
        
        # ترتيب الملفات حسب تاريخ التعديل (الأحدث أولاً)
        excel_files.sort(key=lambda f: os.path.getmtime(os.path.join(export_dir, f)), reverse=True)
        latest_excel = os.path.join(export_dir, excel_files[0])
        
        logger.info(f"تحليل أحدث ملف إكسل: {latest_excel}")
        
        # تحليل الملف
        analysis_results = analyze_excel_file(latest_excel)
        if not analysis_results:
            logger.error("فشل تحليل ملف الإكسل")
            return
        
        # إنشاء تقرير التحليل
        report_path = generate_analysis_report(analysis_results)
        if report_path:
            print(f"تم إنشاء تقرير التحليل بنجاح: {report_path}")
            
            # عرض مخطط توزيع الصفوف الدراسية إذا كان موجوداً
            if 'grade_chart_path' in analysis_results:
                print(f"تم إنشاء مخطط توزيع الصفوف الدراسية: {analysis_results['grade_chart_path']}")
        else:
            print("فشل إنشاء تقرير التحليل")
    
    except Exception as e:
        logger.error(f"خطأ غير متوقع: {e}")
        print(f"حدث خطأ أثناء التنفيذ: {e}")

if __name__ == "__main__":
    main()
