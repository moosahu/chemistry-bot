# -*- coding: utf-8 -*-
"""Handles communication with the external Chemistry API."""

import logging
import requests # Using requests library
from requests.exceptions import RequestException, Timeout

# Import config variables
try:
    from config import API_BASE_URL, API_TIMEOUT, logger
except ImportError:
    # Fallback if config is not available (should not happen in normal operation)
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config. Using fallback settings for API client.")
    API_BASE_URL = "http://localhost:8000/api" # Dummy URL
    API_TIMEOUT = 10

def fetch_from_api(endpoint: str, params: dict = None):
    """Fetches data from the specified API endpoint.

    Args:
        endpoint: The API endpoint path (e.g., 
'/questions', 
'/courses/1/units').
        params: Optional dictionary of query parameters.

    Returns:
        The JSON response as a dictionary or list if successful,
        "TIMEOUT" if the request times out,
        None if any other error occurs.
    """
    if not API_BASE_URL or API_BASE_URL.startswith("http://your-api-base-url.com"):
        logger.error(f"[API] Invalid or missing API_BASE_URL (
'{API_BASE_URL}
'). Cannot fetch from endpoint: 
{endpoint}
")
        return None

    url = f" {API_BASE_URL.rstrip(
'/'
)}/
{endpoint.lstrip(
'/'
)}
"
    logger.debug(f"[API] Fetching data from: 
{url}
 with params: 
{params}
")

    try:
        response = requests.get(url, params=params, timeout=API_TIMEOUT)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        logger.debug(f"[API] Received response status: 
{response.status_code}
")
        # Check if response is empty or not valid JSON
        try:
            json_response = response.json()
            logger.debug(f"[API] Response JSON: 
{json_response}
")
            return json_response
        except requests.exceptions.JSONDecodeError:
            logger.error(f"[API] Failed to decode JSON response from 
{url}
. Response text: 
{response.text[:200]}
...")
            return None

    except Timeout:
        logger.error(f"[API] Timeout error when fetching from 
{url}
 after 
{API_TIMEOUT}
 seconds.")
        return "TIMEOUT"
    except RequestException as e:
        logger.error(f"[API] Request error fetching from 
{url}
: 
{e}
")
        return None
    except Exception as e:
        logger.exception(f"[API] Unexpected error fetching from 
{url}
: 
{e}
")
        return None

def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a question dictionary from the API format to the internal format.

    Args:
        api_question: A dictionary representing a question from the API.

    Returns:
        A dictionary in the internal format, or None if the input is invalid.
    """
    if not isinstance(api_question, dict):
        logger.warning(f"[API_TRANSFORM] Invalid input: Expected dict, got 
{type(api_question)}
")
        return None

    try:
        # --- Basic Fields ---
        question_id = api_question.get(
'id'
) or api_question.get(
'question_id'
) # Allow both 'id' and 'question_id'
        question_text = api_question.get(
'question_text'
)
        image_url = api_question.get(
'image_url'
)
        explanation = api_question.get(
'explanation'
)

        # --- Options --- 
        # Expecting options in a list or as separate fields
        options_list = [None] * 4 # Initialize with 4 None values
        if 
'options'
 in api_question and isinstance(api_question[
'options'
], list):
            # Assuming options list contains text strings
            api_options = api_question[
'options'
]
            for i in range(min(len(api_options), 4)):
                options_list[i] = api_options[i]
        else:
            # Try fetching individual option fields
            options_list[0] = api_question.get(
'option1'
) or api_question.get(
'option_1'
)
            options_list[1] = api_question.get(
'option2'
) or api_question.get(
'option_2'
)
            options_list[2] = api_question.get(
'option3'
) or api_question.get(
'option_3'
)
            options_list[3] = api_question.get(
'option4'
) or api_question.get(
'option_4'
)

        # --- Correct Answer --- 
        # Expecting a zero-based index (0, 1, 2, 3)
        correct_answer_index = api_question.get(
'correct_answer'
) # Could be index or text
        correct_option_index = api_question.get(
'correct_option_index'
) # Prefer explicit index

        final_correct_index = None
        if correct_option_index is not None and isinstance(correct_option_index, int) and 0 <= correct_option_index < 4:
            final_correct_index = correct_option_index
        elif correct_answer_index is not None:
            if isinstance(correct_answer_index, int) and 0 <= correct_answer_index < 4:
                final_correct_index = correct_answer_index
            elif isinstance(correct_answer_index, str):
                # Try to find the index matching the correct answer text
                try:
                    final_correct_index = options_list.index(correct_answer_index)
                except ValueError:
                    logger.warning(f"[API_TRANSFORM] Correct answer text '
{correct_answer_index}
' not found in options: 
{options_list}
 for q_id: 
{question_id}
")
                    final_correct_index = None # Cannot determine index

        # --- Validation --- 
        if not question_id or not question_text:
            logger.warning(f"[API_TRANSFORM] Missing question_id or question_text in API data: 
{api_question}
")
            return None
        if final_correct_index is None:
            logger.warning(f"[API_TRANSFORM] Could not determine valid correct_answer index (0-3) for q_id: 
{question_id}
. Data: 
{api_question}
")
            return None
        if all(opt is None for opt in options_list):
             logger.warning(f"[API_TRANSFORM] All options are None for q_id: 
{question_id}
. Data: 
{api_question}
")
             # Allow this case for now, maybe it's a different question type?

        # --- Construct Internal Format --- 
        internal_question = {
            "question_id": question_id,
            "question_text": question_text,
            "option1": options_list[0],
            "option2": options_list[1],
            "option3": options_list[2],
            "option4": options_list[3],
            "correct_answer": final_correct_index, # Store the 0-based index
            "explanation": explanation,
            "image_url": image_url,
            # Add placeholders for image options if API supports them
            "option1_image": api_question.get(
'option1_image'
),
            "option2_image": api_question.get(
'option2_image'
),
            "option3_image": api_question.get(
'option3_image'
),
            "option4_image": api_question.get(
'option4_image'
),
        }
        logger.debug(f"[API_TRANSFORM] Transformed question (id: 
{question_id}
): 
{internal_question}
")
        return internal_question

    except Exception as e:
        logger.exception(f"[API_TRANSFORM] Error transforming API question data: 
{api_question}
. Error: 
{e}
")
        return None

