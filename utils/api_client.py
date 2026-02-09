# -*- coding: utf-8 -*-
"""Handles communication with the external Chemistry API.
MODIFIED v2: Converted to async using aiohttp for better performance.
             Kept sync fallback (fetch_from_api_sync) for backward compatibility.
"""

import logging
import aiohttp
import uuid

# Import config variables
try:
    from config import API_BASE_URL, API_TIMEOUT, logger
except ImportError:
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config. Using fallback settings for API client.")
    API_BASE_URL = "http://localhost:8000/api"
    API_TIMEOUT = 10

# === Synchronous fallback using requests (kept for backward compatibility) ===
import requests
from requests.exceptions import RequestException, Timeout

def fetch_from_api_sync(endpoint: str, params: dict = None):
    """Synchronous version - kept for backward compatibility."""
    if not API_BASE_URL or API_BASE_URL.startswith("http://your-api-base-url.com"):
        logger.error(f"[API-SYNC] Invalid API_BASE_URL: '{API_BASE_URL}'")
        return None

    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    logger.debug(f"[API-SYNC] Fetching: {url}")

    try:
        response = requests.get(url, params=params, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Timeout:
        logger.error(f"[API-SYNC] Timeout: {url}")
        return "TIMEOUT"
    except RequestException as e:
        logger.error(f"[API-SYNC] Error: {url}: {e}")
        return None
    except Exception as e:
        logger.exception(f"[API-SYNC] Unexpected: {url}: {e}")
        return None


# === Async version using aiohttp ===
async def fetch_from_api(endpoint: str, params: dict = None):
    """Fetches data from the specified API endpoint asynchronously.

    Args:
        endpoint: The API endpoint path.
        params: Optional dictionary of query parameters.

    Returns:
        The JSON response if successful,
        "TIMEOUT" if the request times out,
        None if any other error occurs.
    """
    if not API_BASE_URL or API_BASE_URL.startswith("http://your-api-base-url.com"):
        logger.error(f"[API-ASYNC] Invalid API_BASE_URL: '{API_BASE_URL}'")
        return None

    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    logger.debug(f"[API-ASYNC] Fetching: {url} params: {params}")

    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                logger.debug(f"[API-ASYNC] Status: {response.status}")

                if response.status >= 400:
                    logger.error(f"[API-ASYNC] HTTP {response.status} from {url}")
                    return None

                try:
                    return await response.json()
                except Exception:
                    text = await response.text()
                    logger.error(f"[API-ASYNC] JSON decode failed: {url}. Text: {text[:200]}")
                    return None

    except aiohttp.ServerTimeoutError:
        logger.error(f"[API-ASYNC] Timeout: {url} after {API_TIMEOUT}s")
        return "TIMEOUT"
    except aiohttp.ClientError as e:
        logger.error(f"[API-ASYNC] Client error: {url}: {e}")
        return None
    except Exception as e:
        logger.exception(f"[API-ASYNC] Unexpected: {url}: {e}")
        return None


def transform_api_question(api_question: dict) -> dict | None:
    """Transforms a question from API format to internal QuizLogic format."""
    if not isinstance(api_question, dict):
        logger.warning(f"[API_TRANSFORM] Invalid input: Expected dict, got {type(api_question)}")
        return None

    try:
        question_id = api_question.get('id') or api_question.get('question_id')
        question_text = api_question.get('question_text')
        question_image_url = api_question.get('image_url')
        explanation = api_question.get('explanation')

        if not question_id:
            return None
        if not question_text and not question_image_url:
            return None

        api_options = api_question.get('options')
        if not isinstance(api_options, list) or not api_options:
            return None

        internal_options = []
        has_correct = False

        for i, opt in enumerate(api_options):
            if not isinstance(opt, dict):
                continue

            content = opt.get('image_url') or opt.get('option_text')
            if content is None:
                continue

            is_correct = opt.get('is_correct', False)
            if is_correct:
                has_correct = True

            opt_id = opt.get('id') or opt.get('option_id') or f"gen_opt_{question_id}_{i}_{uuid.uuid4().hex[:6]}"

            internal_options.append({
                "option_id": str(opt_id),
                "option_text": content,
                "is_correct": bool(is_correct)
            })

        if len(internal_options) < 2 or not has_correct:
            return None

        return {
            "question_id": str(question_id),
            "question_text": question_text,
            "image_url": question_image_url,
            "explanation": explanation,
            "options": internal_options
        }

    except Exception as e:
        logger.exception(f"[API_TRANSFORM] Error transforming question: {e}")
        return None
