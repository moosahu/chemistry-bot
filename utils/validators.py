"""
Input validation utilities for the quiz system.

This module provides validation functions to ensure all user inputs
and data from external sources are valid, safe, and within acceptable ranges.
"""

import re
import html
from typing import Optional, Union

# Use try-except to handle both relative and absolute imports
try:
    from .exceptions import (
        InvalidQuestionCountError,
        InvalidCourseIdError,
        InvalidUnitIdError,
        InvalidAnswerError
    )
except ImportError:
    from utils.exceptions import (
        InvalidQuestionCountError,
        InvalidCourseIdError,
        InvalidUnitIdError,
        InvalidAnswerError
    )


def validate_question_count(
    count: Union[str, int],
    max_questions: int,
    min_questions: int = 1
) -> int:
    """Validate and convert question count to integer.
    
    Args:
        count: Question count as string or integer
        max_questions: Maximum allowed questions
        min_questions: Minimum allowed questions (default: 1)
        
    Returns:
        Validated question count as integer
        
    Raises:
        InvalidQuestionCountError: If count is invalid
        
    Examples:
        >>> validate_question_count("10", 50)
        10
        >>> validate_question_count(5, 50)
        5
        >>> validate_question_count("abc", 50)
        InvalidQuestionCountError: ...
    """
    # Convert to integer if string
    try:
        count_int = int(count)
    except (ValueError, TypeError):
        raise InvalidQuestionCountError(
            f"❌ '{count}' ليس رقماً صحيحاً\n\n"
            f"يرجى إدخال رقم بين {min_questions} و {max_questions}"
        )
    
    # Check minimum
    if count_int < min_questions:
        raise InvalidQuestionCountError(
            f"❌ عدد الأسئلة يجب أن يكون على الأقل {min_questions}"
        )
    
    # Check maximum
    if count_int > max_questions:
        raise InvalidQuestionCountError(
            f"❌ عدد الأسئلة يتجاوز الحد الأقصى\n\n"
            f"الحد الأقصى: {max_questions}\n"
            f"العدد المطلوب: {count_int}"
        )
    
    return count_int


def validate_course_id(course_id: Union[str, int]) -> int:
    """Validate and convert course ID to integer.
    
    Args:
        course_id: Course ID as string or integer
        
    Returns:
        Validated course ID as integer
        
    Raises:
        InvalidCourseIdError: If course ID is invalid
        
    Examples:
        >>> validate_course_id("42")
        42
        >>> validate_course_id(42)
        42
        >>> validate_course_id("abc")
        InvalidCourseIdError: ...
    """
    try:
        course_id_int = int(course_id)
    except (ValueError, TypeError):
        raise InvalidCourseIdError(
            f"❌ معرف المقرر '{course_id}' غير صالح\n\n"
            "يرجى اختيار مقرر من القائمة"
        )
    
    if course_id_int < 1:
        raise InvalidCourseIdError(
            "❌ معرف المقرر يجب أن يكون رقماً موجباً"
        )
    
    return course_id_int


def validate_unit_id(unit_id: Union[str, int]) -> int:
    """Validate and convert unit ID to integer.
    
    Args:
        unit_id: Unit ID as string or integer
        
    Returns:
        Validated unit ID as integer
        
    Raises:
        InvalidUnitIdError: If unit ID is invalid
        
    Examples:
        >>> validate_unit_id("15")
        15
        >>> validate_unit_id(15)
        15
        >>> validate_unit_id("xyz")
        InvalidUnitIdError: ...
    """
    try:
        unit_id_int = int(unit_id)
    except (ValueError, TypeError):
        raise InvalidUnitIdError(
            f"❌ معرف الوحدة '{unit_id}' غير صالح\n\n"
            "يرجى اختيار وحدة من القائمة"
        )
    
    if unit_id_int < 1:
        raise InvalidUnitIdError(
            "❌ معرف الوحدة يجب أن يكون رقماً موجباً"
        )
    
    return unit_id_int


def validate_user_id(user_id: Union[str, int]) -> int:
    """Validate and convert user ID to integer.
    
    Args:
        user_id: User ID as string or integer
        
    Returns:
        Validated user ID as integer
        
    Raises:
        ValueError: If user ID is invalid
    """
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid user ID: {user_id}")
    
    if user_id_int < 1:
        raise ValueError("User ID must be positive")
    
    return user_id_int


def validate_option_id(option_id: str, available_options: list) -> str:
    """Validate that option ID exists in available options.
    
    Args:
        option_id: The option ID to validate
        available_options: List of valid option dictionaries
        
    Returns:
        Validated option ID
        
    Raises:
        InvalidAnswerError: If option ID is not valid
    """
    if not option_id:
        raise InvalidAnswerError("❌ لم يتم تحديد إجابة")
    
    # Extract option IDs from available options
    valid_option_ids = [
        str(opt.get("option_id"))
        for opt in available_options
        if opt.get("option_id") is not None
    ]
    
    if str(option_id) not in valid_option_ids:
        raise InvalidAnswerError(
            "❌ الإجابة المحددة غير صالحة\n\n"
            "يرجى اختيار إجابة من الخيارات المتاحة"
        )
    
    return str(option_id)


def sanitize_text_input(
    text: str,
    max_length: int = 1000,
    allow_newlines: bool = True
) -> str:
    """Sanitize user text input to prevent injection attacks.
    
    This function removes or escapes potentially dangerous characters
    while preserving legitimate text content.
    
    Args:
        text: Raw user input text
        max_length: Maximum allowed length (default: 1000)
        allow_newlines: Whether to allow newline characters (default: True)
        
    Returns:
        Sanitized text safe for storage and display
        
    Examples:
        >>> sanitize_text_input("Hello World")
        'Hello World'
        >>> sanitize_text_input("<script>alert('xss')</script>")
        '&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;'
    """
    if not isinstance(text, str):
        return ""
    
    # HTML escape to prevent XSS
    text = html.escape(text)
    
    # Remove SQL injection attempts
    sql_patterns = [
        r"(\bDROP\b|\bDELETE\b|\bINSERT\b|\bUPDATE\b)",
        r"(--|;|\/\*|\*\/)",
        r"(\bUNION\b.*\bSELECT\b)",
    ]
    for pattern in sql_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    
    # Remove command injection attempts
    text = text.replace("|", "").replace("&", "&amp;")
    text = text.replace(">", "&gt;").replace("<", "&lt;")
    
    # Remove null bytes
    text = text.replace("\x00", "")
    
    # Handle newlines
    if not allow_newlines:
        text = text.replace("\n", " ").replace("\r", " ")
    
    # Limit length
    text = text[:max_length]
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


def validate_time_limit(time_limit: Union[str, int, float]) -> int:
    """Validate time limit for questions.
    
    Args:
        time_limit: Time limit in seconds
        
    Returns:
        Validated time limit as integer
        
    Raises:
        ValueError: If time limit is invalid
    """
    try:
        time_limit_int = int(time_limit)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid time limit: {time_limit}")
    
    # Minimum 10 seconds
    if time_limit_int < 10:
        raise ValueError("Time limit must be at least 10 seconds")
    
    # Maximum 10 minutes (600 seconds)
    if time_limit_int > 600:
        raise ValueError("Time limit cannot exceed 10 minutes")
    
    return time_limit_int


def validate_quiz_name(name: str) -> str:
    """Validate and sanitize quiz name.
    
    Args:
        name: Quiz name
        
    Returns:
        Validated and sanitized quiz name
        
    Raises:
        ValueError: If name is invalid
    """
    if not name or not isinstance(name, str):
        raise ValueError("Quiz name is required")
    
    # Sanitize
    name = sanitize_text_input(name, max_length=200, allow_newlines=False)
    
    # Check length after sanitization
    if len(name) < 3:
        raise ValueError("Quiz name must be at least 3 characters")
    
    return name


def validate_page_number(page: Union[str, int], max_pages: int) -> int:
    """Validate pagination page number.
    
    Args:
        page: Page number
        max_pages: Maximum number of pages
        
    Returns:
        Validated page number (0-indexed)
        
    Raises:
        ValueError: If page number is invalid
    """
    try:
        page_int = int(page)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid page number: {page}")
    
    if page_int < 0:
        raise ValueError("Page number must be non-negative")
    
    if page_int >= max_pages:
        raise ValueError(f"Page number exceeds maximum ({max_pages - 1})")
    
    return page_int


def is_valid_callback_data(callback_data: str, expected_prefix: str) -> bool:
    """Check if callback data has the expected format.
    
    Args:
        callback_data: Callback data from button press
        expected_prefix: Expected prefix (e.g., "quiz_type_", "answer_")
        
    Returns:
        True if callback data is valid, False otherwise
    """
    if not isinstance(callback_data, str):
        return False
    
    if not callback_data.startswith(expected_prefix):
        return False
    
    # Check for suspicious patterns
    suspicious_patterns = [";", "--", "DROP", "DELETE", "INSERT", "<script>"]
    callback_lower = callback_data.lower()
    
    for pattern in suspicious_patterns:
        if pattern.lower() in callback_lower:
            return False
    
    return True
