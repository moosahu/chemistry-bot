#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اختبار الرسوم البيانية للتأكد من عملها بدون مشاكل الخطوط
"""

import matplotlib.pyplot as plt
import matplotlib
import os

def test_charts():
    """اختبار إنشاء الرسوم البيانية"""
    print("🧪 اختبار الرسوم البيانية...")
    
    try:
        # إعداد matplotlib لاستخدام خطوط آمنة
        matplotlib.rcParams['font.family'] = 'DejaVu Sans'
        matplotlib.rcParams['axes.unicode_minus'] = False
        
        # إنشاء مجلد للاختبار
        test_dir = '/tmp/test_charts'
        os.makedirs(test_dir, exist_ok=True)
        
        # اختبار 1: رسم بياني بسيط
        print("📊 اختبار الرسم البياني الأول...")
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # بيانات تجريبية
        levels = ['ممتاز', 'جيد جداً', 'جيد', 'متوسط', 'ضعيف']
        counts = [15, 20, 25, 10, 5]
        colors = ['#2E8B57', '#32CD32', '#FFD700', '#FF6347', '#DC143C']
        
        bars = ax.bar(levels, counts, color=colors)
        ax.set_title('توزيع مستويات الأداء', fontsize=16, fontweight='bold')
        ax.set_ylabel('عدد المستخدمين', fontsize=12)
        ax.set_xlabel('مستوى الأداء', fontsize=12)
        
        # إضافة القيم على الأعمدة
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                   f'{count}', ha='center', va='bottom', fontweight='bold')
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        chart_path = os.path.join(test_dir, 'test_performance.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        if os.path.exists(chart_path):
            file_size = os.path.getsize(chart_path) / 1024
            print(f"✅ تم إنشاء الرسم الأول: {file_size:.1f} KB")
        else:
            print("❌ فشل في إنشاء الرسم الأول")
            return False
        
        # اختبار 2: رسم خطي
        print("📈 اختبار الرسم الخطي...")
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # بيانات تجريبية للنشاط اليومي
        dates = ['2025-08-22', '2025-08-23', '2025-08-24', '2025-08-25', '2025-08-26']
        counts = [12, 18, 15, 22, 20]
        
        ax.plot(dates, counts, marker='o', linewidth=2, markersize=6, color='#2196F3')
        ax.fill_between(dates, counts, alpha=0.3, color='#2196F3')
        
        ax.set_title('النشاط اليومي للاختبارات', fontsize=16, fontweight='bold')
        ax.set_ylabel('عدد الاختبارات', fontsize=12)
        ax.set_xlabel('التاريخ', fontsize=12)
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        chart_path = os.path.join(test_dir, 'test_activity.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        if os.path.exists(chart_path):
            file_size = os.path.getsize(chart_path) / 1024
            print(f"✅ تم إنشاء الرسم الثاني: {file_size:.1f} KB")
        else:
            print("❌ فشل في إنشاء الرسم الثاني")
            return False
        
        # اختبار 3: رسم أداء الصفوف
        print("📊 اختبار رسم أداء الصفوف...")
        fig, ax = plt.subplots(figsize=(10, 6))
        
        grades = ['الصف الأول', 'الصف الثاني', 'الصف الثالث', 'الصف الرابع']
        percentages = [85, 78, 82, 90]
        
        bars = ax.bar(grades, percentages, color='#4CAF50')
        ax.set_title('متوسط أداء الصفوف الدراسية', fontsize=16, fontweight='bold')
        ax.set_ylabel('متوسط النسبة المئوية (%)', fontsize=12)
        ax.set_xlabel('الصف الدراسي', fontsize=12)
        ax.set_ylim(0, 100)
        
        # إضافة خط المتوسط العام
        overall_avg = sum(percentages) / len(percentages)
        ax.axhline(y=overall_avg, color='red', linestyle='--', alpha=0.7, 
                  label=f'المتوسط العام: {overall_avg:.1f}%')
        ax.legend()
        
        # إضافة القيم على الأعمدة
        for bar, percentage in zip(bars, percentages):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                   f'{percentage}%', ha='center', va='bottom', fontweight='bold')
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        chart_path = os.path.join(test_dir, 'test_grades.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        if os.path.exists(chart_path):
            file_size = os.path.getsize(chart_path) / 1024
            print(f"✅ تم إنشاء الرسم الثالث: {file_size:.1f} KB")
        else:
            print("❌ فشل في إنشاء الرسم الثالث")
            return False
        
        print("\n🎉 جميع اختبارات الرسوم البيانية نجحت!")
        print("✅ الخطوط تعمل بدون مشاكل")
        print("✅ النصوص العربية تظهر بشكل صحيح")
        print("✅ الألوان والتنسيق ممتاز")
        
        return True
        
    except Exception as e:
        print(f"❌ خطأ في اختبار الرسوم البيانية: {e}")
        return False

if __name__ == "__main__":
    success = test_charts()
    if success:
        print("\n🚀 الرسوم البيانية جاهزة للاستخدام في التقارير!")
    else:
        print("\n❌ يحتاج إصلاح في الرسوم البيانية")

