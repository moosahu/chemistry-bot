# -*- coding: utf-8 -*-
"""Handles communication with the external Chemistry API.
MODIFIED v1: transform_api_question now creates a structured 'options' list 
             to support text/image options robustly for QuizLogic.
"""

import logging
import requests # Using requests library
from requests.exceptions import RequestException, Timeout
import uuid # For generating option_ids if not provided

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
'/questions
', 
'/courses/1/units
').
        params: Optional dictionary of query parameters.

    Returns:
        The JSON response as a dictionary or list if successful,
        "TIMEOUT" if the request times out,
        None if any other error occurs.
    """
    if not API_BASE_URL or API_BASE_URL.startswith("http://your-api-base-url.com"):
        logger.error(f"[API] Invalid or missing API_BASE_URL (	'{API_BASE_URL}	'). Cannot fetch from endpoint: {endpoint}")
        return None

    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    logger.debug(f"[API] Fetching data from: {url} with params: {params}")

    try:
        response = requests.get(url, params=params, timeout=API_TIMEOUT)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        logger.debug(f"[API] Received response status: {response.status_code}")
        try:
            json_response = response.json()
            return json_response
        except requests.exceptions.JSONDecodeError:
            logger.error(f"[API] Failed to decode JSON response from {url}. Response text: {response.text[:200]}...")
            return None

    except Timeout:
        logger.error(f"[API] Timeout error when fetching from {url} after {API_TIMEOUT} seconds.")
        return "TIMEOUT"
    except RequestException as e:
        logger.error(f"[API] Request error fetching from {url}: {e}")
        return None
    except Exception as e:
        logger.exception(f"[API] Unexpected error fetching from {url}: {e}")
        return None

def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a question dictionary from the API format to the internal format
    that QuizLogic expects. Specifically, it creates an 'options' list where each
    option is a dict: {'option_id': str, 'option_text': str (text or URL), 'is_correct': bool}.

    Args:
        api_question: A dictionary representing a question from the API.
                      Expected format includes 'id', 'question_text', 'image_url' (optional),
                      'explanation' (optional), and 'options' (list of dicts).
                      Each API option dict should have 'option_text' (optional for text content),
                      'image_url' (optional for image URL content), and 'is_correct' (boolean).
                      An API option might also have an 'id' or 'option_id'.

    Returns:
        A dictionary in the internal format, or None if the input is invalid.
    """
    if not isinstance(api_question, dict):
        logger.warning(f"[API_TRANSFORM] Invalid input: Expected dict, got {type(api_question)}")
        return None

    try:
        question_id = api_question.get('id') or api_question.get('question_id')
        question_text = api_question.get('question_text')
        question_image_url = api_question.get('image_url') # Main question image
        explanation = api_question.get('explanation')

        if not question_id:
            logger.warning(f"[API_TRANSFORM] Missing question_id in API data: {api_question}")
            return None
        if not question_text and not question_image_url:
            logger.warning(f"[API_TRANSFORM] Missing both question_text and image_url for q_id: {question_id}. Data: {api_question}")
            return None

        api_options_from_payload = api_question.get('options')
        if not isinstance(api_options_from_payload, list) or not api_options_from_payload:
            logger.warning(f"[API_TRANSFORM] Missing or invalid 'options' list for q_id: {question_id}. Data: {api_question}")
            return None

        internal_options_list = []
        correct_answer_found_in_options = False

        for i, api_opt_data in enumerate(api_options_from_payload):
            if not isinstance(api_opt_data, dict):
                logger.warning(f"[API_TRANSFORM] Invalid item in API 'options' list (not a dict) for q_id: {question_id}. Item: {api_opt_data}")
                continue

            option_content = None
            # Prefer image_url if present for the option's content
            if api_opt_data.get('image_url'):
                option_content = api_opt_data['image_url']
            elif api_opt_data.get('option_text'):
                option_content = api_opt_data['option_text']
            
            if option_content is None:
                logger.warning(f"[API_TRANSFORM] API Option {i} for q_id: {question_id} has no 'image_url' or 'option_text'. Skipping. Data: {api_opt_data}")
                continue

            is_correct = api_opt_data.get('is_correct', False)
            if is_correct:
                correct_answer_found_in_options = True
            
            # Get option_id from API if available, otherwise generate one
            option_id = api_opt_data.get('id') or api_opt_data.get('option_id') or f"gen_opt_{question_id}_{i}_{uuid.uuid4().hex[:6]}"

            internal_options_list.append({
                "option_id": str(option_id),
                "option_text": option_content, # This will be processed by QuizLogic (text or URL)
                "is_correct": bool(is_correct)
            })

        if len(internal_options_list) < 2:
            logger.warning(f"[API_TRANSFORM] Less than 2 valid options constructed for q_id: {question_id}. Found {len(internal_options_list)}. API Data: {api_question}")
            return None
        
        if not correct_answer_found_in_options:
            logger.warning(f"[API_TRANSFORM] No correct answer (is_correct: True) found among valid options for q_id: {question_id}. API Data: {api_question}")
            return None

        internal_question = {
            "question_id": str(question_id),
            "question_text": question_text,
            "image_url": question_image_url, # Main question image
            "explanation": explanation,
            "options": internal_options_list # Structured list of options for QuizLogic
        }
        # logger.debug(f"[API_TRANSFORM] Transformed question (id: {question_id}): {internal_question}")
        return internal_question

    except Exception as e:
        logger.exception(f"[API_TRANSFORM] Error transforming API question data: {api_question}. Error: {e}")
        return None

