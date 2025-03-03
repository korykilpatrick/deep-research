import os
import sys
from dotenv import load_dotenv
load_dotenv(override=True)

from openai import AsyncOpenAI
from openai.types import ChatModel
from openai.types.chat.chat_completion import ChatCompletion
import tiktoken
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import anthropic
from anthropic.types import Model
import asyncio
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import Any, Dict, Optional, Callable, Awaitable, List, Literal

# Environment Variables
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_ENDPOINT: str = os.getenv("OPENAI_API_ENDPOINT", "https://api.openai.com/v1")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "o3-mini")
CONTEXT_SIZE: int = int(os.getenv("CONTEXT_SIZE", 128000))
FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_BASE_URL: str = os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev/v1")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Exit if necessary API keys are missing
if not OPENAI_API_KEY and not ANTHROPIC_API_KEY:
    print("Warning: Must include OPENAI_API_KEY, ANTHROPIC_API_KEY, or both. Please ensure one or more is defined in your .env file.")
    sys.exit(1)
if not FIRECRAWL_API_KEY:
    print("Warning: FIRECRAWL_API_KEY is not set. Please ensure it is defined in your .env file.")
    sys.exit(1)

# Provider type
ProviderType = Literal["openai", "anthropic"]

# Configure clients based on available API keys
openai_client = None
anthropic_client = None

try:
    if OPENAI_API_KEY:
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_ENDPOINT)
except Exception as e:
    print(f"Error initializing OpenAI client: {str(e)}")

try:
    if ANTHROPIC_API_KEY:
        anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
except Exception as e:
    print(f"Error initializing Anthropic client: {str(e)}")

class ModelInfo:
    def __init__(self, model=None, model_params=None):
        self.model = model or OPENAI_MODEL
        if self.model == 'o3-mini':
            self.model = 'o3-mini-2025-01-31'
        
        self.model_params = model_params or {}
        if "temperature" not in self.model_params:
            self.model_params["temperature"] = 0.3
            
        # Determine provider based on model name by trying to retrieve the model from each provider
        self.provider: Optional[ProviderType] = None
        
        if self.model.startswith("o"):
            self.model_params.pop("temperature", None)
        
        if self.model in ChatModel.__args__:
            self.provider = "openai"
        elif self.model in Model.__args__[0].__args__:
            self.provider = "anthropic"
        else:
            # We'll need to do this synchronously during initialization
            try:
                # Try to use an existing event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an event loop, we need to create a new one for this task
                    asyncio.run_coroutine_threadsafe(self._determine_provider(), loop).result()
                else:
                    # If there's a loop but it's not running, we can use it
                    loop.run_until_complete(self._determine_provider())
            except RuntimeError:
                # If no event loop exists, create one
                asyncio.run(self._determine_provider())
    
    async def _determine_provider(self):
        """Determine which provider can handle the specified model."""
        errors = []
        matches = []
        
        # Try OpenAI first
        if openai_client:
            try:
                await openai_client.models.retrieve(self.model)
                matches.append("openai")
            except Exception as e:
                # Model not found in OpenAI, continue to next provider
                errors.append(f"OpenAI error: {str(e)}")
        else:
            errors.append("OpenAI client not configured (missing API key)")
        
        # Try Anthropic next
        if anthropic_client:
            try:
                await anthropic_client.models.retrieve(self.model)
                matches.append("anthropic")
            except Exception as e:
                # Model not found in Anthropic
                errors.append(f"Anthropic error: {str(e)}")
        else:
            errors.append("Anthropic client not configured (missing API key)")
        
        # Determine the provider based on matches
        if len(matches) > 0:
            # If multiple providers match, prefer OpenAI (first in matches list)
            self.provider = matches[0]
            if len(matches) > 1:
                print(f"Warning: Model '{self.model}' is available in multiple providers ({', '.join(matches)}). Using {self.provider}.")
            return
            
        # If we get here, no provider could handle the model
        error_details = "\n - " + "\n - ".join(errors)
        raise Exception(f"Model '{self.model}' not found in any configured provider. Please check the model name and ensure the corresponding API key is set. Details: {error_details}")

MIN_CHUNK_SIZE: int = 140
tokenizer = tiktoken.get_encoding("o200k_base")

# Add the custom retry class below the imports
class ConstantBackoffRetry(Retry):
    """
    Custom Retry class that always returns a constant 1s backoff time for retries.
    """
    def get_backoff_time(self) -> float:
        # If there is any retry history, return a constant 5 second delay.
        return 10.0 if self.history else 3.0

def trim_prompt(prompt: str, context_size: int = CONTEXT_SIZE) -> str:
    """Trim the prompt recursively to ensure the token count fits within context_size."""
    if not prompt:
        return ""
    token_count = len(tokenizer.encode(prompt))
    if token_count <= context_size:
        return prompt
    overflow_tokens = token_count - context_size
    chunk_size = len(prompt) - (overflow_tokens * 3)
    if chunk_size < MIN_CHUNK_SIZE:
        return prompt[:MIN_CHUNK_SIZE]

    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=0)
    chunks = splitter.split_text(prompt)
    if not chunks:
        return ""
    trimmed = chunks[0]
    # If the chunk is still the same size as the whole prompt, do a direct cut
    if len(trimmed) == len(prompt):
        return trim_prompt(prompt[:chunk_size], context_size)
    return trim_prompt(trimmed, context_size)

def _get_retry_session(total: int = 3, backoff_factor: float = 1, status_forcelist: Optional[list] = None) -> requests.Session:
    if status_forcelist is None:
        status_forcelist = [429, 500, 502, 503, 504]
    session = requests.Session()
    # Use the custom ConstantBackoffRetry which enforces a 1s sleep before retrying
    retries = ConstantBackoffRetry(
        total=total,
        backoff_factor=backoff_factor,  # Note: This value is not used as get_backoff_time is overridden.
        status_forcelist=status_forcelist,
        allowed_methods=["POST"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def firecrawl_search(query: str, timeout: int = 15000, limit: int = 5,
                     scrape_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search via Firecrawl using default scrape options (markdown) by making a direct requests call.
    Implements retry logic for handling rate limits and transient errors.
    """
    if not FIRECRAWL_API_KEY:
        raise Exception("FIRECRAWL_API_KEY not configured. Please set in .env file.")

    if scrape_options is None:
        scrape_options = {}

    clean_query = query.strip().strip('"')
    if not clean_query:
        raise Exception("Empty query after cleaning")

    print(f"Making Firecrawl request to: {FIRECRAWL_BASE_URL}/search")
    print(f"Query: {clean_query}")

    url = f"{FIRECRAWL_BASE_URL}/search"
    payload = {
        "query": clean_query,
        "limit": limit,
        "timeout": timeout,
        "tbs": "",
        "lang": "en",
        "country": "us",
        "location": "",
        "scrapeOptions": scrape_options
    }
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json"
    }

    session = _get_retry_session()
    try:
        response = session.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("success"):
            return result
        else:
            print(f"Unexpected response format: {result}")
            return {"data": []}
    except Exception as e:
        print(f"Firecrawl error details: {str(e)}")
        print(f"Error type: {type(e)}")
        return {"data": []}

def get_model(model_info: Optional[ModelInfo] = None) -> Callable[..., Awaitable[Dict[str, Any]]]:
    """
    Returns an async callable that calls the appropriate model API based on the provider.
    - For OpenAI models, uses the chat.completions.create endpoint with appropriate parameters
    - For Anthropic models, uses the messages.create endpoint with appropriate parameters
    
    Each provider's specific parameters are handled appropriately.
    """
    model_info = model_info or ModelInfo()
    extra_params: Dict[str, Any] = model_info.model_params.copy()
    
    # Set provider-specific parameters
    if model_info.provider == "openai":
        # Set OpenAI-specific defaults
        if model_info.model.startswith("o") and not extra_params.get("reasoning_effort"):
            extra_params["reasoning_effort"] = "medium"
    elif model_info.provider == "anthropic":
        # Set Anthropic-specific defaults
        if not extra_params.get("max_tokens"):
            extra_params["max_tokens"] = 8192 if not extra_params.get("thinking") else 64000
        # # For Claude 3.7+ models, add thinking parameter if not already specified
        if model_info.model.startswith("claude-3-7") and extra_params.get("thinking"):
            if type(extra_params["thinking"]) != dict:
                extra_params["thinking"] = {"type": "enabled", "budget_tokens": 8192}
            else:
                if "type" not in extra_params["thinking"]:
                    extra_params["thinking"]["type"] = "enabled"
                if "budget_tokens" not in extra_params["thinking"]:
                    extra_params["thinking"]["budget_tokens"] = 8192

    async def call_model(prompt: str, **kwargs: Any) -> Dict[str, Any]:
        params = {**extra_params, **kwargs}
        
        try:
            if model_info.provider == "openai":
                # Handle OpenAI-specific parameters
                if not openai_client:
                    raise Exception("OpenAI client not properly configured")
                    
                response = await openai_client.chat.completions.create(
                    model=model_info.model,
                    messages=[
                        {"role": "system", "content": "You are an expert research assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    **params
                )
                return response
                
            elif model_info.provider == "anthropic":
                # Handle Anthropic-specific parameters
                if not anthropic_client:
                    raise Exception("Anthropic client not properly configured")
                    
                anthropic_params = params.copy()
                
                # Remove OpenAI-specific parameters
                for param in ["reasoning_effort"]:
                    if param in anthropic_params:
                        del anthropic_params[param]
                
                if 'reportMarkdown' in prompt:
                    prompt += "\n\nRemember that all newlines should be escaped with \\n in the JSON response."
                anthropic_response = await anthropic_client.messages.create(
                    model=model_info.model,
                    system="You are an expert research assistant.",
                    messages=[{"role": "user", "content": prompt}],
                    **anthropic_params
                )
                
                # Convert Anthropic response to match OpenAI structure for consistent interface
                response = {
                    "id": anthropic_response.id,
                    "model": anthropic_response.model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": anthropic_response.content[0].text,
                        },
                        "finish_reason": anthropic_response.stop_reason
                    }],
                    "usage": {
                        "prompt_tokens": anthropic_response.usage.input_tokens,
                        "completion_tokens": anthropic_response.usage.output_tokens,
                        "total_tokens": anthropic_response.usage.input_tokens + anthropic_response.usage.output_tokens
                    },
                    "_original_response": anthropic_response
                }
                try:
                    response = ChatCompletion.construct(**response)
                except:
                    pass
                return response
                
            else:
                raise Exception(f"Unknown model provider: {model_info.provider}")
                
        except Exception as e:
            # Add context to the error message to make debugging easier
            error_message = f"Error calling {model_info.provider} model '{model_info.model}': {str(e)}"
            print(error_message)
            # Re-raise the exception with more context
            raise Exception(error_message) from e

    return call_model
