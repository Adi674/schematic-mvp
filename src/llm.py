"""
Mistral AI LLM & Multimodal Vision Integration.
Provides direct, robust API calls to Mistral API using requests / mistralai SDK.
"""

import os
import base64
import json
from typing import List, Dict, Any, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")


def encode_image_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode('utf-8')


import sys

def safe_print(text: str) -> None:
    """Safely prints text on any terminal encoding (e.g. Windows cp1252)."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or 'utf-8'
        print(text.encode(encoding, errors='replace').decode(encoding))


class MistralAPIError(Exception):
    """Custom exception raised when a call to Mistral API fails."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def call_mistral_text(system_prompt: str, user_prompt: str, model: str = "mistral-small-latest") -> str:
    """
    Calls Mistral API for text composition and synthesis.
    Raises MistralAPIError if the API key is missing or the request fails.
    """
    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        raise MistralAPIError("MISTRAL_API_KEY is not set in environment or .env file.", status_code=500)

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            return content
        else:
            raise MistralAPIError(
                f"Mistral API returned status {res.status_code}: {res.text}",
                status_code=res.status_code
            )
    except MistralAPIError:
        raise
    except Exception as e:
        raise MistralAPIError(f"Exception during Mistral API request: {e}", status_code=500)


def call_mistral_vision(
    image_bytes: bytes,
    prompt: str,
    model: str = "mistral-small-latest",
    mime_type: str = "image/png",
    response_format: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Calls Mistral Multimodal Vision API for schematic image extraction.

    Args:
        image_bytes: Raw image bytes.
        prompt: Text prompt for extraction.
        model: Mistral model alias.
        mime_type: Actual image MIME type ('image/png' or 'image/jpeg').
                   Must match the uploaded file's actual format.
        response_format: Optional structured output schema for JSON enforcement.
    """
    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        safe_print("[VISION LLM] Notice: MISTRAL_API_KEY is not set in environment or .env file.")
        return None

    # Sanitize MIME type — Mistral supports image/png and image/jpeg
    if mime_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        safe_print(f"[VISION LLM] Unsupported MIME type '{mime_type}', defaulting to image/png")
        mime_type = "image/png"
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    safe_print(f"\n{'='*30} [VISION LLM REQUEST] {'='*30}")
    safe_print(f"Model: {model} | MIME: {mime_type} | Image payload size: {len(image_bytes)} bytes")
    safe_print(f"--- Vision Extraction Prompt ---\n{prompt.strip()}")

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    base64_image = encode_image_base64(image_bytes)
    image_data_url = f"data:{mime_type};base64,{base64_image}"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_data_url}
                ]
            }
        ],
        "temperature": 0.1
    }

    # Attach structured output schema if provided (Mistral supports response_format)
    if response_format:
        payload["response_format"] = response_format

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            safe_print(f"\n--- [VISION LLM RAW RESPONSE] ---\n{content}\n{'='*75}\n")
            return content
        else:
            safe_print(f"[VISION LLM ERROR] Status code {res.status_code}: {res.text}")
            return None
    except Exception as e:
        safe_print(f"[VISION LLM ERROR] Exception during request: {e}")
        return None


