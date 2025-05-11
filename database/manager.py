
    def get_score_distribution(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching score distribution for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "completed_at")
        query = f"""
        SELECT
            CASE
                WHEN score_percentage >= 90 THEN 9 -- Bin for 90-100%
                ELSE FLOOR(score_percentage / 10)
            END AS score_bin_index, 
            COUNT(*) AS count
        FROM quiz_results
        WHERE completed_at IS NOT NULL AND score_percentage >= 0 AND score_percentage <= 100 {time_condition}
        GROUP BY score_bin_index
        ORDER BY score_bin_index;
        """
        result = self._execute_query(query, fetch_all=True)
        # Ensure result is a list of dicts, even if empty or None
        return result if result is not None else []

    def get_quiz_completion_rate_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching quiz completion rate stats for filter: {time_filter}")
        
        # Total started quizzes
        time_condition_started = self._get_time_filter_condition(time_filter, "start_time")
        query_started = f"SELECT COUNT(result_id) as total_started FROM quiz_results WHERE 1=1 {time_condition_started};"
        result_started = self._execute_query(query_started, fetch_one=True)
        total_started = result_started["total_started"] if result_started and "total_started" in result_started else 0

        # Total completed quizzes
        time_condition_completed = self._get_time_filter_condition(time_filter, "completed_at")
        query_completed = f"SELECT COUNT(result_id) as total_completed FROM quiz_results WHERE completed_at IS NOT NULL {time_condition_completed};"
        result_completed = self._execute_query(query_completed, fetch_one=True)
        total_completed = result_completed["total_completed"] if result_completed and "total_completed" in result_completed else 0
        
        logger.info(f"[DB Admin Stats] Completion rate: Started={total_started}, Completed={total_completed} for filter: {time_filter}")
        return {"total_started": total_started, "total_completed": total_completed}

    def get_question_difficulty_stats(self, time_filter="all"):
        logger.info(f"[DB Admin Stats] Fetching question difficulty stats for filter: {time_filter}")
        time_condition = self._get_time_filter_condition(time_filter, "qr.completed_at")
        
        # Assuming 'questions' table has 'question_id' (PK) and 'question_text'.
        # And 'quiz_results.answers_details' is JSONB: [{'question_id': id, 'is_correct': bool}, ...]
        query = f"""
        WITH question_attempts AS (
            SELECT
                (answer_detail ->> 'question_id')::int AS question_id,
                (answer_detail ->> 'is_correct')::boolean AS is_correct
            FROM quiz_results qr,
                 jsonb_array_elements(qr.answers_details) AS answer_detail
            WHERE qr.completed_at IS NOT NULL 
              AND qr.answers_details IS NOT NULL 
              AND jsonb_typeof(qr.answers_details) = 'array' -- Ensure it's an array
              AND jsonb_array_length(qr.answers_details) > 0 -- Ensure array is not empty
              {time_condition}
        )
        SELECT
            qa.question_id AS id,
            q.question_text AS text,
            SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) AS correct_answers,
            COUNT(qa.question_id) AS total_attempts,
            (SUM(CASE WHEN qa.is_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(qa.question_id)) AS correct_percentage
        FROM question_attempts qa
        JOIN questions q ON qa.question_id = q.question_id
        GROUP BY qa.question_id, q.question_text
        HAVING COUNT(qa.question_id) > 0 -- Only include questions with attempts
        ORDER BY total_attempts DESC, correct_percentage ASC; -- Hardest or most attempted first
        """
        
        stats = self._execute_query(query, fetch_all=True)
        if stats:
            logger.info(f"[DB Admin Stats] Found {len(stats)} questions with difficulty stats for filter: {time_filter}")
            # The query already calculates correct_percentage. Ensure field names match expectations.
            # Expected: {'id': q_id, 'text': q_text, 'correct_percentage': diff_perc, 'attempts': attempts_count}
            # Current from query: {'id': q_id, 'text': q_text, 'correct_answers': N, 'total_attempts': M, 'correct_percentage': P}
            # We can directly return this if admin_dashboard_display.py uses 'correct_percentage' and 'total_attempts'
            return stats
        else:
            logger.warning(f"[DB Admin Stats] No question difficulty stats found for filter: {time_filter}")
            return []

# Ensure this is the end of the DatabaseManager class or adjust indentation if it's not.

