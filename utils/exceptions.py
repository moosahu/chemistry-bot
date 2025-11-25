"""
Custom exceptions for the quiz system.

This module defines all custom exceptions used throughout the quiz application
to provide clear, specific error handling and user-friendly error messages.
"""


class QuizError(Exception):
    """Base exception for all quiz-related errors.
    
    All custom quiz exceptions should inherit from this class.
    This allows for catching all quiz-specific errors with a single except clause.
    """
    pass


class QuizNotFoundError(QuizError):
    """Raised when a requested quiz is not found.
    
    This can occur when:
    - A saved quiz has been deleted
    - An invalid quiz ID is provided
    - A quiz session has expired
    """
    pass


class NoQuestionsFoundError(QuizError):
    """Raised when no questions are available for the requested criteria.
    
    This can occur when:
    - A course has no questions
    - A unit has no questions
    - All questions have been used recently
    """
    pass


class InvalidQuestionCountError(QuizError):
    """Raised when the requested question count is invalid.
    
    This can occur when:
    - Question count is not a number
    - Question count is negative or zero
    - Question count exceeds available questions
    - Question count exceeds maximum allowed
    """
    pass


class InvalidCourseIdError(QuizError):
    """Raised when an invalid course ID is provided.
    
    This can occur when:
    - Course ID is not a number
    - Course ID doesn't exist in the database
    - Course has been deleted
    """
    pass


class InvalidUnitIdError(QuizError):
    """Raised when an invalid unit ID is provided.
    
    This can occur when:
    - Unit ID is not a number
    - Unit ID doesn't exist in the database
    - Unit has been deleted
    """
    pass


class APIConnectionError(QuizError):
    """Raised when connection to external API fails.
    
    This can occur when:
    - Network connection is unavailable
    - API server is down
    - Request timeout
    - Authentication failure
    """
    pass


class DatabaseConnectionError(QuizError):
    """Raised when database connection fails.
    
    This can occur when:
    - Database server is down
    - Connection pool exhausted
    - Authentication failure
    - Network issues
    """
    pass


class QuizSessionExpiredError(QuizError):
    """Raised when a quiz session has expired.
    
    This can occur when:
    - User took too long to complete quiz
    - Session was manually terminated
    - System restart cleared sessions
    """
    pass


class InvalidAnswerError(QuizError):
    """Raised when an invalid answer is provided.
    
    This can occur when:
    - Answer format is incorrect
    - Answer ID doesn't match any option
    - Answer is for wrong question
    """
    pass


class QuizAlreadyActiveError(QuizError):
    """Raised when trying to start a quiz while another is active.
    
    This prevents users from having multiple concurrent quiz sessions.
    """
    pass


class SavedQuizLimitExceededError(QuizError):
    """Raised when user tries to save more quizzes than allowed.
    
    This enforces the maximum number of saved quizzes per user.
    """
    pass


class RateLimitExceededError(QuizError):
    """Raised when user exceeds rate limit for quiz operations.
    
    This can occur when:
    - Too many quizzes started in short time
    - Too many API requests
    - Suspected abuse
    """
    pass


def get_user_friendly_message(exception: Exception) -> str:
    """Convert exception to user-friendly Arabic message.
    
    Args:
        exception: The exception to convert
        
    Returns:
        User-friendly error message in Arabic
    """
    error_messages = {
        QuizNotFoundError: (
            "⚠️ عذراً، الاختبار المطلوب غير موجود\n\n"
            "يمكنك:\n"
            "• بدء اختبار جديد\n"
            "• العودة للقائمة الرئيسية"
        ),
        NoQuestionsFoundError: (
            "⚠️ عذراً، لا توجد أسئلة متاحة حالياً\n\n"
            "يمكنك:\n"
            "• اختيار مقرر آخر\n"
            "• تقليل عدد الأسئلة\n"
            "• العودة للقائمة الرئيسية"
        ),
        InvalidQuestionCountError: (
            "❌ عدد الأسئلة غير صالح\n\n"
            "يرجى إدخال رقم صحيح ضمن الحدود المسموحة"
        ),
        InvalidCourseIdError: (
            "❌ المقرر المحدد غير صالح\n\n"
            "يرجى اختيار مقرر من القائمة"
        ),
        InvalidUnitIdError: (
            "❌ الوحدة المحددة غير صالحة\n\n"
            "يرجى اختيار وحدة من القائمة"
        ),
        APIConnectionError: (
            "⚠️ حدث خطأ في الاتصال بالخادم\n\n"
            "يرجى:\n"
            "• التحقق من اتصال الإنترنت\n"
            "• المحاولة مرة أخرى بعد قليل\n"
            "• التواصل مع الدعم إذا استمرت المشكلة"
        ),
        DatabaseConnectionError: (
            "⚠️ حدث خطأ في قاعدة البيانات\n\n"
            "يرجى المحاولة مرة أخرى بعد قليل\n"
            "إذا استمرت المشكلة، يرجى التواصل مع الدعم"
        ),
        QuizSessionExpiredError: (
            "⏱️ انتهت صلاحية جلسة الاختبار\n\n"
            "يمكنك بدء اختبار جديد من القائمة الرئيسية"
        ),
        InvalidAnswerError: (
            "❌ الإجابة المقدمة غير صالحة\n\n"
            "يرجى اختيار إجابة من الخيارات المتاحة"
        ),
        QuizAlreadyActiveError: (
            "⚠️ لديك اختبار نشط بالفعل\n\n"
            "يرجى إنهاء الاختبار الحالي أولاً"
        ),
        SavedQuizLimitExceededError: (
            "⚠️ وصلت للحد الأقصى من الاختبارات المحفوظة\n\n"
            "يرجى إنهاء أو حذف بعض الاختبارات المحفوظة أولاً"
        ),
        RateLimitExceededError: (
            "⚠️ عدد كبير من المحاولات\n\n"
            "يرجى الانتظار قليلاً قبل المحاولة مرة أخرى"
        ),
    }
    
    exception_type = type(exception)
    
    # Check if we have a specific message for this exception type
    if exception_type in error_messages:
        return error_messages[exception_type]
    
    # Check if the exception has a custom message
    if str(exception):
        return str(exception)
    
    # Default generic error message
    return (
        "⚠️ حدث خطأ غير متوقع\n\n"
        "تم تسجيل المشكلة وسيتم حلها قريباً.\n"
        "يرجى المحاولة لاحقاً أو التواصل مع الدعم."
    )
