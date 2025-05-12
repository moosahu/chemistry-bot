        # ... (other admin functions)

    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        
        query = f"""
        SELECT 
            CASE 
                WHEN score_percentage >= 0 AND score_percentage <= 10 THEN '0-10%'
                WHEN score_percentage > 10 AND score_percentage <= 20 THEN '11-20%'
                WHEN score_percentage > 20 AND score_percentage <= 30 THEN '21-30%'
                WHEN score_percentage > 30 AND score_percentage <= 40 THEN '31-40%'
                WHEN score_percentage > 40 AND score_percentage <= 50 THEN '41-50%'
                WHEN score_percentage > 50 AND score_percentage <= 60 THEN '51-60%'
                WHEN score_percentage > 60 AND score_percentage <= 70 THEN '61-70%'
                WHEN score_percentage > 70 AND score_percentage <= 80 THEN '71-80%'
                WHEN score_percentage > 80 AND score_percentage <= 90 THEN '81-90%'
                WHEN score_percentage > 90 AND score_percentage <= 100 THEN '91-100%'
                ELSE 'N/A'
            END as score_range,
            COUNT(result_id) as count
        FROM quiz_results
        WHERE completed_at IS NOT NULL {time_condition}
        GROUP BY score_range
        ORDER BY 
            CASE score_range
                WHEN '0-10%' THEN 1
                WHEN '11-20%' THEN 2
                WHEN '21-30%' THEN 3
                WHEN '31-40%' THEN 4
                WHEN '41-50%' THEN 5
                WHEN '51-60%' THEN 6
                WHEN '61-70%' THEN 7
                WHEN '71-80%' THEN 8
                WHEN '81-90%' THEN 9
                WHEN '91-100%' THEN 10
                ELSE 11
            END;
        """
        raw_result = self._execute_query(query, fetch_all=True)
        logger.info(f"[DB Admin Stats V17] Raw result for score_distribution ({time_filter}): {raw_result}")
        
        # Ensure all ranges are present, even if count is 0, and in correct order
        expected_ranges = ['0-10%', '11-20%', '21-30%', '31-40%', '41-50%', '51-60%', '61-70%', '71-80%', '81-90%', '91-100%']
        result_map = {item['score_range']: item['count'] for item in raw_result if item and 'score_range' in item}
        
        distribution = []
        for r in expected_ranges:
            distribution.append({'score_range': r, 'count': result_map.get(r, 0)})
            
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No score distribution data found for filter: {time_filter}. Returning empty distribution for all ranges.")

        return distribution

    def get_average_score_percentage(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching average score percentage for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"SELECT COALESCE(AVG(score_percentage), 0.0) as average_score FROM quiz_results WHERE completed_at IS NOT NULL {time_condition};"
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for average_score_percentage ({time_filter}): {raw_result}")
        return raw_result["average_score"] if raw_result and "average_score" in raw_result else 0.0

    def get_overall_average_score(self, time_filter="all") -> float:
        logger.info(f"[DB Admin Stats V17] Fetching overall average score (alias for get_average_score_percentage) for filter: {time_filter}")
        return self.get_average_score_percentage(time_filter)

    def get_average_quizzes_per_active_user(self, time_filter="all") -> float:
        logger.info(f"[DB Admin Stats V17] Fetching average quizzes per active user for filter: {time_filter}")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")
        time_condition_user = self._get_time_filter_condition(time_filter, "last_interaction_date")

        query = f"""
        WITH active_users_count AS (
            SELECT COUNT(DISTINCT user_id) as count FROM users WHERE 1=1 {time_condition_user}
        ),
        completed_quizzes_count AS (
            SELECT COUNT(result_id) as count FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_quiz}
        )
        SELECT 
            CASE 
                WHEN (SELECT count FROM active_users_count) > 0 THEN 
                    CAST((SELECT count FROM completed_quizzes_count) AS FLOAT) / (SELECT count FROM active_users_count)
                ELSE 0.0 
            END as average_quizzes_per_active_user;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for average_quizzes_per_active_user ({time_filter}): {raw_result}")
        return raw_result["average_quizzes_per_active_user"] if raw_result and "average_quizzes_per_active_user" in raw_result else 0.0

    def get_quiz_completion_rate_stats(self, time_filter="all") -> dict:
        logger.info(f"[DB Admin Stats V17] Fetching quiz completion rate stats for filter: {time_filter}")
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        # For started quizzes, we might use 'start_time' or 'created_at' of the quiz_results entry
        # Assuming 'created_at' for quiz_results is when it's initiated.
        # If quiz_results are only created on start, then 'created_at' is fine.
        # If not, and 'start_time' is more reliable, use that.
        # For this example, let's assume 'start_time' is reliably populated upon quiz start.
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")

        query = f"""
        SELECT 
            (SELECT COUNT(result_id) FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed}) as completed_count,
            (SELECT COUNT(result_id) FROM quiz_results WHERE start_time IS NOT NULL {time_condition_started}) as attempted_count;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for quiz_completion_rate_stats ({time_filter}): {raw_result}")

        completed_count = 0
        attempted_count = 0
        completion_rate_percentage = 0.0

        if raw_result:
            completed_count = raw_result.get("completed_count", 0)
            attempted_count = raw_result.get("attempted_count", 0)
            if attempted_count > 0:
                completion_rate_percentage = (completed_count / attempted_count) * 100
            else:
                completion_rate_percentage = 0.0 # Avoid division by zero, or 100% if completed_count is also 0
                if completed_count == 0 and attempted_count == 0:
                     completion_rate_percentage = 0.0 # Or based on preference, could be 100% if no attempts means 100% completion of 0 tasks
        
        return {
            "completed_count": completed_count,
            "attempted_count": attempted_count,
            "completion_rate_percentage": round(completion_rate_percentage, 2)
        }

    def get_questions_difficulty_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching questions difficulty distribution for filter: {time_filter}")
        # This requires a more complex query involving answers_details and questions table if difficulty is stored there.
        # For now, returning a placeholder as this was not in the original scope of the error.
        # A proper implementation would parse answers_details (JSONB) to link questions to their correct/incorrect counts.
        logger.warning("[DB Admin Stats V17] get_questions_difficulty_distribution is a placeholder and not fully implemented.")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")

        # Placeholder query - this will NOT give actual difficulty per question from answers_details
        # It gives a general idea of how many times questions were part of completed quizzes.
        # A real implementation needs to unnest answers_details and join with questions table.
        query = f"""
        SELECT 
            q.question_id,
            q.text as question_text,
            COUNT(DISTINCT qr.result_id) as quizzes_included_in, -- How many quizzes included this question (approx)
            SUM(CASE WHEN ad.value->>'is_correct' = 'true' THEN 1 ELSE 0 END) as total_correct,
            SUM(CASE WHEN ad.value->>'is_correct' = 'false' THEN 1 ELSE 0 END) as total_incorrect
        FROM questions q
        LEFT JOIN quiz_results qr ON qr.completed_at IS NOT NULL {time_condition}
        CROSS JOIN LATERAL jsonb_array_elements(qr.answers_details) ad
        WHERE (ad.value->>'question_id')::int = q.question_id -- Ensure question_id is cast to int if it's text in JSON
        GROUP BY q.question_id, q.text
        ORDER BY q.question_id
        LIMIT 20; -- Limit for now, as this can be large
        """
        # The above query is an example and might need significant adjustments based on actual answers_details structure.
        # It's also computationally intensive.
        # A simpler version might just count correct/incorrect from a dedicated table if that exists.

        # For now, returning a simplified structure or an empty list:
        raw_result = self._execute_query(query, fetch_all=True) # This query is illustrative and likely needs refinement
        logger.info(f"[DB Admin Stats V17] Raw result for question_difficulty ({time_filter}): {raw_result}")
        
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No question difficulty data found for filter: {time_filter}. Returning empty list.")
            return []
        return raw_result

    def get_user_engagement_metrics(self, time_filter="all"):
        logger.info(f"[DB Admin Stats V17] Fetching user engagement metrics for filter: {time_filter}")
        time_condition_interaction = self._get_time_filter_condition(time_filter, "last_interaction_date")
        time_condition_quiz = self._get_time_filter_condition(time_filter, "completed_at")

        query = f"""
        SELECT 
            (SELECT COUNT(DISTINCT user_id) FROM users WHERE 1=1 {time_condition_interaction}) as active_users,
            (SELECT COUNT(result_id) FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_quiz}) as total_completed_quizzes,
            (SELECT COALESCE(AVG(time_taken_seconds), 0.0) FROM quiz_results WHERE completed_at IS NOT NULL AND time_taken_seconds IS NOT NULL {time_condition_quiz}) as average_quiz_duration_seconds;
        """
        raw_result = self._execute_query(query, fetch_one=True)
        logger.info(f"[DB Admin Stats V17] Raw result for user_engagement_metrics ({time_filter}): {raw_result}")
        
        if not raw_result:
            logger.warning(f"[DB Admin Stats V17] No user engagement data found for filter: {time_filter}. Returning defaults.")
            return {"active_users": 0, "total_completed_quizzes": 0, "average_quiz_duration_seconds": 0.0}
        return raw_result

    # Add other specific admin stat functions here as needed...

# Example usage (for testing, not part of the class normally)
if __name__ == "__main__":
    # Configure logging for standalone testing
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Testing DatabaseManager standalone...")
    db_manager = DatabaseManager()

    # Test a simple query
    # courses = db_manager.get_all_courses()
    # logger.info(f"Courses: {courses}")

    # Test admin stats
    logger.info(f"Total users: {db_manager.get_total_users_count()}")
    logger.info(f"Active users (today): {db_manager.get_active_users_count('today')}")
    logger.info(f"Total quizzes (all time): {db_manager.get_total_quizzes_count('all')}")
    logger.info(f"Average score (last 7 days): {db_manager.get_average_score_percentage('last_7_days')}")
    logger.info(f"Score Distribution (all time): {db_manager.get_score_distribution('all')}")
    logger.info(f"Quiz Completion Rate (all time): {db_manager.get_quiz_completion_rate_stats('all')}")
    logger.info(f"Average Quizzes per Active User (all time): {db_manager.get_average_quizzes_per_active_user('all')}")
    logger.info(f"Question Difficulty (all time): {db_manager.get_questions_difficulty_distribution('all')}") # Placeholder
    logger.info(f"User Engagement (all time): {db_manager.get_user_engagement_metrics('all')}")

    # Test user registration
    # db_manager.register_or_update_user(12345, "Test", "User", "testuser", "en")
    # logger.info(f"Is 12345 admin? {db_manager.is_user_admin(12345)}")

    # Test leaderboard
    # logger.info(f"Leaderboard: {db_manager.get_leaderboard()}")

    # Test user stats
    # logger.info(f"User 12345 stats: {db_manager.get_user_overall_stats(12345)}")
    # logger.info(f"User 12345 recent history: {db_manager.get_user_recent_quiz_history(12345)}")

    logger.info("Standalone test finished.")

