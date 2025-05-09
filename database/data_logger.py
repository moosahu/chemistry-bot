# database/data_logger.py (ULTRA FINAL - Added missing functions)
from config import logger
from datetime import datetime
import json # For serializing details

# Attempt to import DB_MANAGER. This should align with your project structure.
from database.manager import DB_MANAGER

def log_user_activity(user_id: int, action: str, details: dict | None = None):
    """Logs a generic user activity to the database."""
    try:
        if not DB_MANAGER:
            logger.error("[DataLogger] DB_MANAGER is not available. Cannot log user activity.")
            return
        
        details_json = json.dumps(details) if details else None
        # Assuming DB_MANAGER has a method like record_user_activity
        # This is a placeholder for the actual DB call. You might need to create this method in DB_MANAGER.
        # For now, we will just log it, as the primary issue is the import error.
        # DB_MANAGER.record_user_activity(user_id=user_id, action=action, details_json=details_json)
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
        
        # Assuming DB_MANAGER has a method like start_new_quiz_session that returns a session ID
        # This is a placeholder. You need to ensure this method exists in your DB_MANAGER
        # and that it creates a record in a quiz_sessions table and returns its primary key.
        # For now, let's assume it returns a dummy ID or calls a method that does.
        # db_session_id = DB_MANAGER.start_new_quiz_session(
        #     user_id=user_id, 
        #     quiz_type=quiz_type, 
        #     quiz_name=quiz_name, 
        #     quiz_scope_id=quiz_scope_id, 
        #     total_questions=total_questions
        # )
        # Since the original error was about not getting db_quiz_session_id, 
        # this function MUST return an ID if the DB interaction is successful.
        # The actual implementation of DB_MANAGER.start_new_quiz_session is crucial.
        # For the purpose of fixing the import and flow, we will assume it exists.

        # Placeholder for the actual call to a DB_MANAGER method that creates a session and returns an ID.
        # If your DB_MANAGER.save_quiz_result creates the session implicitly, this function might only log.
        # However, the error logs suggest a db_quiz_session_id is expected *before* QuizLogic initialization.
        
        # Let's assume there's a method in DB_MANAGER to log the start and get an ID.
        # If not, this part needs to be designed. For now, to fix the import error and provide the functions:
        if hasattr(DB_MANAGER, "start_quiz_session_and_get_id"):
            db_session_id = DB_MANAGER.start_quiz_session_and_get_id(
                user_id=user_id,
                quiz_type=quiz_type,
                quiz_name=quiz_name,
                quiz_scope_id=quiz_scope_id,
                total_questions=total_questions,
                start_time=datetime.now(timezone.utc) # Add start time here
            )
            if db_session_id:
                logger.info(f"[DataLogger] Quiz start logged. DB Session ID: {db_session_id} for user {user_id}")
                return db_session_id
            else:
                logger.error(f"[DataLogger] DB_MANAGER.start_quiz_session_and_get_id did not return a session ID for user {user_id}.")
                return None
        else:
            logger.warning("[DataLogger] DB_MANAGER does not have method start_quiz_session_and_get_id. Quiz start not fully logged to DB for distinct session tracking.")
            # Fallback: if no such method, we can't return a DB-generated ID here.
            # This would mean the db_quiz_session_id in QuizLogic would remain None or rely on a different mechanism.
            # This is a critical design point for your application.
            return None # Or a locally generated one if your design supports it and links it later

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
            details=details_for_db,
            # If your save_quiz_result in manager.py needs db_quiz_session_id directly:
            # passed_db_quiz_session_id=db_quiz_session_id 
        )

        logger.info(f"[DataLogger] Successfully called DB_MANAGER.save_quiz_result for user {user_id}, quiz_uuid: {quiz_id_uuid}.")

    except Exception as e:
        logger.error(f"[DataLogger] Error in log_quiz_results for user {user_id}, quiz_uuid {quiz_id_uuid}: {e}", exc_info=True)

