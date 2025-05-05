# -*- coding: utf-8 -*-
"""Handles communication with the external Chemistry API (Corrected v1 - Flexible question transform)."""

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

    url = f" {API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}
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
            # logger.debug(f"[API] Response JSON: 
{json_response}
") # Can be very verbose
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
    Handles variable number of options and determines correct answer from 'is_correct' flag.

    Args:
        api_question: A dictionary representing a question from the API.
                      Expected format includes 'id', 'question_text', 'image_url' (optional),
                      'explanation' (optional), and 'options' (list of dicts).
                      Each option dict should have 'option_text' (optional), 'image_url' (optional),
                      and 'is_correct' (boolean).

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
        question_id = api_question.get('id') or api_question.get('question_id')
        question_text = api_question.get('question_text')
        question_image_url = api_question.get('image_url') # Renamed to avoid conflict
        explanation = api_question.get('explanation')

        # --- Validation: Basic Fields ---
        if not question_id:
            logger.warning(f"[API_TRANSFORM] Missing question_id in API data: 
{api_question}
")
            return None
        # Allow questions with only an image
        if not question_text and not question_image_url:
             logger.warning(f"[API_TRANSFORM] Missing both question_text and image_url for q_id: 
{question_id}
. Data: 
{api_question}
")
             return None

        # --- Options and Correct Answer --- 
        api_options = api_question.get('options')
        if not isinstance(api_options, list) or not api_options:
            logger.warning(f"[API_TRANSFORM] Missing or invalid 'options' list for q_id: 
{question_id}
. Data: 
{api_question}
")
            return None

        options_text = [None] * 4
        options_image = [None] * 4
        final_correct_index = None
        valid_options_count = 0

        for i, option_data in enumerate(api_options):
            if i >= 4: # Limit to 4 options for internal format
                logger.warning(f"[API_TRANSFORM] More than 4 options found for q_id: 
{question_id}
. Ignoring extra options.")
                break
            
            if not isinstance(option_data, dict):
                logger.warning(f"[API_TRANSFORM] Invalid item in 'options' list (not a dict) for q_id: 
{question_id}
. Item: 
{option_data}
")
                continue # Skip invalid option

            opt_text = option_data.get('option_text')
            opt_image = option_data.get('image_url')
            is_correct = option_data.get('is_correct')

            # Option must have text or image
            if opt_text is None and opt_image is None:
                 logger.warning(f"[API_TRANSFORM] Option {i} has no text or image for q_id: 
{question_id}
. Option data: 
{option_data}
")
                 continue # Skip invalid option

            options_text[i] = opt_text
            options_image[i] = opt_image
            valid_options_count += 1

            if is_correct is True:
                if final_correct_index is not None:
                    # Should not happen if API is well-formed, but good to check
                    logger.warning(f"[API_TRANSFORM] Multiple correct answers found for q_id: 
{question_id}
. Using first one found (index 
{final_correct_index}
). Data: 
{api_question}
")
                else:
                    final_correct_index = i

        # --- Validation: Options and Correct Answer ---
        if valid_options_count < 2:
             logger.warning(f"[API_TRANSFORM] Less than 2 valid options found for q_id: 
{question_id}
. Data: 
{api_question}
")
             return None # Need at least two options for a meaningful question
             
        if final_correct_index is None:
            logger.warning(f"[API_TRANSFORM] No correct answer found (is_correct: True) for q_id: 
{question_id}
. Data: 
{api_question}
")
            return None
        
        # Check if the correct index points to a valid option that was processed
        if options_text[final_correct_index] is None and options_image[final_correct_index] is None:
             logger.error(f"[API_TRANSFORM] Internal logic error: Correct index 
{final_correct_index}
 points to an invalid/skipped option for q_id: 
{question_id}
. Data: 
{api_question}
")
             return None

        # --- Construct Internal Format --- 
        internal_question = {
            "question_id": question_id,
            "question_text": question_text,
            "option1": options_text[0],
            "option2": options_text[1],
            "option3": options_text[2],
            "option4": options_text[3],
            "correct_answer": final_correct_index, # Store the 0-based index
            "explanation": explanation,
            "image_url": question_image_url, # Use the renamed variable
            "option1_image": options_image[0],
            "option2_image": options_image[1],
            "option3_image": options_image[2],
            "option4_image": options_image[3],
        }
        # logger.debug(f"[API_TRANSFORM] Transformed question (id: 
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

