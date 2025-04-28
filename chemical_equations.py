#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

def process_text_with_chemical_notation(text):
    """
    معالجة النص لتنسيق المعادلات الكيميائية والصيغ الكيميائية.
    
    المعلمات:
        text (str): النص المراد معالجته.
    
    العائد:
        str: النص بعد المعالجة.
    """
    if not text:
        return text
    
    # تحويل الأرقام في الصيغ الكيميائية إلى أرقام منخفضة (subscript)
    # مثال: H2O -> H₂O
    text = re.sub(r'([A-Za-z])(\d+)', lambda m: m.group(1) + ''.join(['₀₁₂₃₄₅₆₇₈₉'[int(d)] for d in m.group(2)]), text)
    
    # تحويل رموز المعادلات
    text = text.replace(' -> ', ' → ')
    text = text.replace(' => ', ' ⇒ ')
    text = text.replace(' <-> ', ' ⇄ ')
    text = text.replace(' <=> ', ' ⇌ ')
    
    return text

def format_chemical_equation(equation):
    """
    تنسيق معادلة كيميائية.
    
    المعلمات:
        equation (str): المعادلة الكيميائية.
    
    العائد:
        str: المعادلة المنسقة.
    """
    return process_text_with_chemical_notation(equation)
