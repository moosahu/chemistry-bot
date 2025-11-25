"""
Structured logging system for the quiz application.

This module provides a structured logging system that outputs logs in JSON format
for easy parsing, analysis, and monitoring.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum


class LogLevel(Enum):
    """Log level enumeration."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    """Quiz event types for structured logging."""
    # Quiz lifecycle events
    QUIZ_STARTED = "quiz_started"
    QUIZ_COMPLETED = "quiz_completed"
    QUIZ_ABANDONED = "quiz_abandoned"
    QUIZ_SAVED = "quiz_saved"
    QUIZ_RESUMED = "quiz_resumed"
    
    # Question events
    QUESTION_SENT = "question_sent"
    QUESTION_ANSWERED = "question_answered"
    QUESTION_SKIPPED = "question_skipped"
    QUESTION_TIMEOUT = "question_timeout"
    
    # User interaction events
    USER_JOINED = "user_joined"
    USER_ACTION = "user_action"
    BUTTON_PRESSED = "button_pressed"
    
    # System events
    ERROR_OCCURRED = "error_occurred"
    API_CALL = "api_call"
    DATABASE_QUERY = "database_query"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    
    # Performance events
    SLOW_OPERATION = "slow_operation"
    RATE_LIMIT_TRIGGERED = "rate_limit_triggered"


class StructuredLogger:
    """Structured logger for quiz events.
    
    This logger outputs all events in JSON format with consistent structure,
    making it easy to parse, search, and analyze logs.
    
    Attributes:
        logger: Underlying Python logger instance
        default_context: Default context added to all log entries
    """
    
    def __init__(self, name: str, default_context: Optional[Dict[str, Any]] = None):
        """Initialize structured logger.
        
        Args:
            name: Logger name (typically module name)
            default_context: Default context to include in all logs
        """
        self.logger = logging.getLogger(name)
        self.default_context = default_context or {}
    
    def _create_log_entry(
        self,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        quiz_id: Optional[str] = None,
        level: str = "INFO"
    ) -> Dict[str, Any]:
        """Create structured log entry.
        
        Args:
            event_type: Type of event
            message: Human-readable message
            data: Additional event data
            user_id: User ID if applicable
            quiz_id: Quiz ID if applicable
            level: Log level
            
        Returns:
            Structured log entry dictionary
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "event_type": event_type,
            "message": message,
        }
        
        # Add user and quiz IDs if provided
        if user_id is not None:
            log_entry["user_id"] = user_id
        
        if quiz_id is not None:
            log_entry["quiz_id"] = quiz_id
        
        # Add default context
        if self.default_context:
            log_entry["context"] = self.default_context
        
        # Add event-specific data
        if data:
            log_entry["data"] = data
        
        return log_entry
    
    def _log(self, log_entry: Dict[str, Any], level: LogLevel):
        """Output log entry at specified level.
        
        Args:
            log_entry: Structured log entry
            level: Log level
        """
        log_message = json.dumps(log_entry, ensure_ascii=False, default=str)
        
        if level == LogLevel.DEBUG:
            self.logger.debug(log_message)
        elif level == LogLevel.INFO:
            self.logger.info(log_message)
        elif level == LogLevel.WARNING:
            self.logger.warning(log_message)
        elif level == LogLevel.ERROR:
            self.logger.error(log_message)
        elif level == LogLevel.CRITICAL:
            self.logger.critical(log_message)
    
    def log_quiz_started(
        self,
        user_id: int,
        quiz_id: str,
        quiz_type: str,
        question_count: int,
        **kwargs
    ):
        """Log quiz start event.
        
        Args:
            user_id: User ID
            quiz_id: Quiz instance ID
            quiz_type: Type of quiz
            question_count: Number of questions
            **kwargs: Additional data
        """
        data = {
            "quiz_type": quiz_type,
            "question_count": question_count,
            **kwargs
        }
        
        log_entry = self._create_log_entry(
            event_type=EventType.QUIZ_STARTED.value,
            message=f"User {user_id} started quiz {quiz_id}",
            data=data,
            user_id=user_id,
            quiz_id=quiz_id,
            level="INFO"
        )
        
        self._log(log_entry, LogLevel.INFO)
    
    def log_quiz_completed(
        self,
        user_id: int,
        quiz_id: str,
        score: int,
        total_questions: int,
        time_taken: float,
        **kwargs
    ):
        """Log quiz completion event.
        
        Args:
            user_id: User ID
            quiz_id: Quiz instance ID
            score: Final score
            total_questions: Total number of questions
            time_taken: Total time taken in seconds
            **kwargs: Additional data
        """
        percentage = (score / total_questions * 100) if total_questions > 0 else 0
        
        data = {
            "score": score,
            "total_questions": total_questions,
            "percentage": round(percentage, 2),
            "time_taken": round(time_taken, 2),
            **kwargs
        }
        
        log_entry = self._create_log_entry(
            event_type=EventType.QUIZ_COMPLETED.value,
            message=f"User {user_id} completed quiz {quiz_id} with score {score}/{total_questions}",
            data=data,
            user_id=user_id,
            quiz_id=quiz_id,
            level="INFO"
        )
        
        self._log(log_entry, LogLevel.INFO)
    
    def log_question_answered(
        self,
        user_id: int,
        quiz_id: str,
        question_id: str,
        is_correct: bool,
        time_taken: float,
        **kwargs
    ):
        """Log question answer event.
        
        Args:
            user_id: User ID
            quiz_id: Quiz instance ID
            question_id: Question ID
            is_correct: Whether answer was correct
            time_taken: Time taken to answer in seconds
            **kwargs: Additional data
        """
        data = {
            "question_id": question_id,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2),
            **kwargs
        }
        
        log_entry = self._create_log_entry(
            event_type=EventType.QUESTION_ANSWERED.value,
            message=f"User {user_id} answered question {question_id} ({'correct' if is_correct else 'incorrect'})",
            data=data,
            user_id=user_id,
            quiz_id=quiz_id,
            level="INFO"
        )
        
        self._log(log_entry, LogLevel.INFO)
    
    def log_error(
        self,
        error_type: str,
        error_message: str,
        user_id: Optional[int] = None,
        quiz_id: Optional[str] = None,
        **kwargs
    ):
        """Log error event.
        
        Args:
            error_type: Type of error
            error_message: Error message
            user_id: User ID if applicable
            quiz_id: Quiz ID if applicable
            **kwargs: Additional error data
        """
        data = {
            "error_type": error_type,
            "error_message": error_message,
            **kwargs
        }
        
        log_entry = self._create_log_entry(
            event_type=EventType.ERROR_OCCURRED.value,
            message=f"Error occurred: {error_type}",
            data=data,
            user_id=user_id,
            quiz_id=quiz_id,
            level="ERROR"
        )
        
        self._log(log_entry, LogLevel.ERROR)
    
    def log_api_call(
        self,
        endpoint: str,
        method: str,
        status_code: Optional[int] = None,
        duration: Optional[float] = None,
        **kwargs
    ):
        """Log API call event.
        
        Args:
            endpoint: API endpoint
            method: HTTP method
            status_code: Response status code
            duration: Request duration in seconds
            **kwargs: Additional data
        """
        data = {
            "endpoint": endpoint,
            "method": method,
            **kwargs
        }
        
        if status_code is not None:
            data["status_code"] = status_code
        
        if duration is not None:
            data["duration"] = round(duration, 3)
        
        level = "INFO"
        if status_code and status_code >= 400:
            level = "WARNING" if status_code < 500 else "ERROR"
        
        log_entry = self._create_log_entry(
            event_type=EventType.API_CALL.value,
            message=f"API call: {method} {endpoint}",
            data=data,
            level=level
        )
        
        self._log(log_entry, LogLevel[level])
    
    def log_slow_operation(
        self,
        operation: str,
        duration: float,
        threshold: float,
        **kwargs
    ):
        """Log slow operation warning.
        
        Args:
            operation: Operation name
            duration: Actual duration in seconds
            threshold: Expected threshold in seconds
            **kwargs: Additional data
        """
        data = {
            "operation": operation,
            "duration": round(duration, 3),
            "threshold": threshold,
            "slowness_factor": round(duration / threshold, 2),
            **kwargs
        }
        
        log_entry = self._create_log_entry(
            event_type=EventType.SLOW_OPERATION.value,
            message=f"Slow operation detected: {operation} took {duration:.2f}s (threshold: {threshold}s)",
            data=data,
            level="WARNING"
        )
        
        self._log(log_entry, LogLevel.WARNING)
    
    def log_user_action(
        self,
        user_id: int,
        action: str,
        **kwargs
    ):
        """Log user action event.
        
        Args:
            user_id: User ID
            action: Action description
            **kwargs: Additional data
        """
        log_entry = self._create_log_entry(
            event_type=EventType.USER_ACTION.value,
            message=f"User {user_id} performed action: {action}",
            data=kwargs,
            user_id=user_id,
            level="INFO"
        )
        
        self._log(log_entry, LogLevel.INFO)


# Global logger instance
quiz_logger = StructuredLogger("quiz_bot")


def configure_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: Optional[str] = None
):
    """Configure logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (if None, logs to console)
        log_format: Log format string (if None, uses default)
    """
    # Set log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Configure handlers
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    handlers.append(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(numeric_level)
        handlers.append(file_handler)
    
    # Set format
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    formatter = logging.Formatter(log_format)
    for handler in handlers:
        handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers and add new ones
    root_logger.handlers = []
    for handler in handlers:
        root_logger.addHandler(handler)
