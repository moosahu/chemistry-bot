# database/data_logger.py (FINAL SCOPE FIX)
from config import logger
from datetime import datetime

# Attempt to import DB_MANAGER. This should align with your project structure.
# If DB_MANAGER is initialized in manager.py and imported as a module instance:
from database.manager import DB_MANAGER

def log_quiz_results(
    user_id: int,
    db_quiz_session_id: int | None, # This was used for logging, can be part of details if needed by DB
    quiz_id_uuid: str, # This is the unique UUID for the quiz instance from QuizLogic
    quiz_name: str,
    quiz_type: str,
    quiz_scope_id: int | None, # <<< Added this parameter
    total_questions: int,
    score: int, # This is the count of correct answers
    wrong_answers: int,
    skipped_answers: int,
    percentage: float,
    start_time: datetime, # Overall quiz start time (datetime object)
    end_time: datetime, # Overall quiz end time (datetime object)
    time_taken_seconds: int | None, # Calculated in QuizLogic, manager also calculates it
    answers_details: list # List of dicts for each question's answer details
):
    """
    Logs the results of a completed quiz to the database via DB_MANAGER.
    Ensures all necessary parameters, including quiz_scope_id and detailed answers,
    are passed correctly.
    """
    try:
        if not DB_MANAGER:
            logger.error("[DataLogger] DB_MANAGER is not available. Cannot log quiz results.")
            return

        logger.info(f"[DataLogger] Preparing to log quiz results for user {user_id}, quiz_uuid: {quiz_id_uuid}, quiz_type: {quiz_type}, quiz_scope_id: {quiz_scope_id}")

        # Construct the 'details' dictionary that DB_MANAGER.save_quiz_result expects.
        # Based on manager_WITH_ANSWERS_DETAILS.py, it primarily uses 'quiz_id_uuid' and 'answers_details' from this dict.
        details_for_db = {
            "quiz_id_uuid": quiz_id_uuid,
            "answers_details": answers_details,
            "quiz_name": quiz_name, # Included for completeness in details, though not a direct column in some schemas
            "db_quiz_session_id": db_quiz_session_id, # Included for completeness
            # time_taken_seconds is calculated by save_quiz_result in the manager from start_time and end_time.
            # If you still want to log the one from quiz_logic, it can be part of details:
            # "time_taken_calculated_in_quiz_logic": time_taken_seconds 
        }

        # Call the save_quiz_result method from DB_MANAGER
        # Ensure the parameter names match what save_quiz_result in your manager.py expects.
        DB_MANAGER.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_type,
            quiz_scope_id=quiz_scope_id,  # Pass the quiz_scope_id
            total_questions=total_questions,
            correct_count=score,          # 'score' from QuizLogic is 'correct_count'
            wrong_count=wrong_answers,
            skipped_count=skipped_answers,
            score_percentage_calculated=percentage,
            start_time=start_time,        # Pass the datetime object
            end_time=end_time,            # Pass the datetime object
            details=details_for_db        # Pass the constructed details dictionary
        )

        logger.info(f"[DataLogger] Successfully called DB_MANAGER.save_quiz_result for user {user_id}, quiz_uuid: {quiz_id_uuid}.")

    except Exception as e:
        logger.error(f"[DataLogger] Error in log_quiz_results for user {user_id}, quiz_uuid {quiz_id_uuid}: {e}", exc_info=True)

