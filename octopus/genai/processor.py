import json
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, ValidationError

from octopus.db.models.prompts import Prompt
from octopus.db.session import session_scope
from openai import AsyncAzureOpenAI
from openai import (
    APIError,
    RateLimitError,
)

from octopus.settings import settings

logger = logging.getLogger(__name__)


class ResponseFormat(Enum):
    """Supported response formats."""
    YAML = "yaml"
    JSON = "json"
    RAW = "raw"


def _clean_code_block(text: str) -> str:
    """Clean and extract content from code blocks in LLM response.
    
    Args:
        text: Raw text that may contain content in code blocks
        
    Returns:
        Cleaned content string
    """
    # Find YAML content between markers if present
    if text.startswith("```"):
        if text.startswith("```yaml"):
            text = text[7:]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

    # Otherwise clean and return the full text
    return text.strip()


def _parse_yaml(text: str) -> Any:
    """Parse YAML text into Python object.
    
    Args:
        text: YAML text to parse
        
    Returns:
        Parsed Python object
        
    Raises:
        yaml.YAMLError: If text is not valid YAML
    """
    return yaml.safe_load(text)


def _parse_json(text: str) -> Any:
    """Parse JSON text into Python object.
    
    Args:
        text: JSON text to parse
        
    Returns:
        Parsed Python object
        
    Raises:
        json.JSONDecodeError: If text is not valid JSON
    """
    return json.loads(text)


class GenAIProcessor:
    """
    Generic processor for LLM interactions.
    Handles model management, retries, and response processing.
    """

    def __init__(self, temperature: float = 0.1, max_retries: int = 2):
        """Initialize the processor with model configuration.

        Args:
            temperature: Temperature for response generation
            max_retries: Maximum number of retries for format validation
        """
        self._max_retries = max_retries
        self._async_llm = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_version,
        )
        self._default_temperature = temperature

    async def _validate_and_parse_response(
        self, text: str, response_format: ResponseFormat
    ) -> Union[str, Dict, List]:
        """Validate and parse response into appropriate format.
        
        Args:
            text: Response text to validate and parse
            response_format: Expected format
            
        Returns:
            Parsed response in appropriate format
            
        Raises:
            ValueError: If validation/parsing fails
        """
        try:
            if response_format == ResponseFormat.YAML:
                return _parse_yaml(text)
            elif response_format == ResponseFormat.JSON:
                return _parse_json(text)
            else:
                return text
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid {response_format.value} format: {str(e)}")

    async def _get_completion(
        self,
        prompt: str,
        temperature: Optional[float],
        max_tokens: int,
    ) -> str:
        """Get completion from LLM.
        
        Args:
            prompt: The prompt to send
            temperature: Optional temperature override
            max_tokens: Maximum tokens in response
            
        Returns:
            Raw response content
        """
        response = await self._async_llm.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.azure_openai_deployment,
            temperature=temperature if temperature is not None else self._default_temperature,
            max_tokens=max_tokens,
            stream=False
        )
        return response.choices[0].message.content

    async def process(
        self,
        prompt: str,
        *,
        response_format: ResponseFormat = ResponseFormat.RAW,
        temperature: Optional[float] = None,
        max_tokens: int = 16_000,
    ) -> Union[str, Dict, List]:
        """Process a prompt with the LLM and return the response.

        Args:
            prompt: The prompt to send to the LLM
            response_format: Expected format of the response
            temperature: Optional override for the temperature
            max_tokens: Maximum number of tokens in the response

        Returns:
            - For RAW format: string response
            - For YAML/JSON format: parsed Python object (dict/list)

        Raises:
            RateLimitError: If the API rate limit is exceeded
            APIError: If there's an error with the Azure OpenAI API
            ValueError: If response validation/parsing fails after retries
        """
        try:
            retries = 0
            original_prompt = prompt
            
            while retries <= self._max_retries:
                content = await self._get_completion(prompt, temperature, max_tokens)
                cleaned_content = _clean_code_block(content)
                
                try:
                    result = await self._validate_and_parse_response(cleaned_content, response_format)
                    
                    # Save prompt to database
                    with session_scope() as db:
                        db_prompt = Prompt(
                            prompt_text=prompt,
                            response_text=cleaned_content,
                            response_format=response_format.value,
                            temperature=str(temperature) if temperature is not None else None,
                            max_tokens=max_tokens,
                        )
                        db.add(db_prompt)
                        db.commit()
                    
                    return result
                except ValueError as e:
                    if retries == self._max_retries:
                        raise
                    
                    retries += 1
                    prompt = (
                        f"Your previous response was not in valid {response_format.value} format. "
                        f"Error: {str(e)}\n"
                        "Please fix the format issues and provide a valid response.\n"
                        f"Original prompt: {original_prompt}"
                    )
                    logger.info("Retrying with format correction, attempt %d", retries)

        except RateLimitError as e:
            logger.error("Rate limit exceeded: %s", str(e))
            raise
        except APIError as e:
            logger.error("Azure OpenAI API error: %s", str(e))
            raise
