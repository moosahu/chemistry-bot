# database/data_logger.py (KWARGS FIX for log_user_activity)
from config import logger
from datetime import datetime, timezone # Ensure timezone is imported
import json # For serializing details

# Attempt to import DB_MANAGER. This should align with your project structure.
from database.manager import DB_MANAGER

def log_user_activity(user_id: int, action: str, details: dict | None = None, **kwargs):
    """Logs a generic user activity to the database, accepting additional keyword arguments."""
    try:
        if not DB_MANAGER:
            logger.error("[DataLogger] DB_MANAGER is not available. Cannot log user activity.")
            return
        
        # Combine provided details with any additional kwargs
        final_details = details if details is not None else {}
        final_details.update(kwargs) # Add all other passed keyword arguments

        details_json = json.dumps(final_details) if final_details else None
        
        # Assuming DB_MANAGER has a method like record_user_activity
        # This is a placeholder for the actual DB call. You might need to create this method in DB_MANAGER.
        # For now, we will just log it.
        # if hasattr(DB_MANAGER, "record_user_activity"):
        #     DB_MANAGER.record_user_activity(user_id=user_id, action=action, details_json=details_json)
        # else:
        #     logger.warning(f"[DataLogger] DB_MANAGER does not have record_user_activity. Logging locally only for user {user_id}.")
        
        logger.info(f"[DataLogger] User activity: User {user_id}, Action: {action}, Details: {details_json}")

    except Exception as e:
        logger.error(f"[DataLogger] Error in log_user_activity for user {user_id}: {e}", exc_info=True)

def log_quiz_start(user_id: int, quiz_type: str, quiz_name: str, quiz_scope_id: int | None, total_questions: int) -> int | None:
    """Logs the start of a quiz and returns a database quiz session ID."""
    try:
        if not DB_MANAGER:
            logger.error("[DataLogger] DB_MANAGER is not available. Cannot log quiz start.")
            return None

        logger.info(f"[DataLogger] Logging quiz start for user {user_id}, Type: {quiz_type}, Name: {quiz_name}, Scope: {quiz_scope_id}")
        
        if hasattr(DB_MANAGER, "start_quiz_session_and_get_id"):
            db_session_id = DB_MANAGER.start_quiz_session_and_get_id(
                user_id=user_id,
                quiz_type=quiz_type,
                quiz_name=quiz_name,
                quiz_scope_id=quiz_scope_id,
                total_questions=total_questions,
                start_time=datetime.now(timezone.utc) 
            )
            if db_session_id:
                logger.info(f"[DataLogger] Quiz start logged. DB Session ID: {db_session_id} for user {user_id}")
                return db_session_id
            else:
                logger.error(f"[DataLogger] DB_MANAGER.start_quiz_session_and_get_id did not return a session ID for user {user_id}.")
                return None
        else:
            logger.warning("[DataLogger] DB_MANAGER does not have method start_quiz_session_and_get_id. Quiz start not fully logged to DB for distinct session tracking.")
            return None

    except Exception as e:
        logger.error(f"[DataLogger] Error in log_quiz_start for user {user_id}: {e}", exc_info=True)
        return None

def log_quiz_results(
    user_id: int,
    db_quiz_session_id: int | None, 
    quiz_id_uuid: str, 
    quiz_name: str,
    quiz_type: str,
    quiz_scope_id: int | None, 
    total_questions: int,
    score: int, 
    wrong_answers: int,
    skipped_answers: int,
    percentage: float,
    start_time: datetime, 
    end_time: datetime, 
    time_taken_seconds: int | None, 
    answers_details: list 
):
    """
    Logs the results of a completed quiz to the database via DB_MANAGER.
    """
    try:
        if not DB_MANAGER:
            logger.error("[DataLogger] DB_MANAGER is not available. Cannot log quiz results.")
            return

        logger.info(f"[DataLogger] Preparing to log quiz results for user {user_id}, quiz_uuid: {quiz_id_uuid}, quiz_type: {quiz_type}, quiz_scope_id: {quiz_scope_id}")

        details_for_db = {
            "quiz_id_uuid": quiz_id_uuid,
            "answers_details": answers_details,
            "quiz_name": quiz_name, 
            "db_quiz_session_id_from_logic": db_quiz_session_id 
        }

        DB_MANAGER.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_type,
            quiz_scope_id=quiz_scope_id,  
            total_questions=total_questions,
            correct_count=score,          
            wrong_count=wrong_answers,
            skipped_count=skipped_answers,
            score_percentage_calculated=percentage,
            start_time=start_time,        
            end_time=end_time,            
            details=details_for_db
        )

        logger.info(f"[DataLogger] Successfully called DB_MANAGER.save_quiz_result for user {user_id}, quiz_uuid: {quiz_id_uuid}.")

    except Exception as e:
        logger.error(f"[DataLogger] Error in log_quiz_results for user {user_id}, quiz_uuid {quiz_id_uuid}: {e}", exc_info=True)

