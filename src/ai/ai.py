import json
import re
from typing import Any, Callable, Optional, Dict, Awaitable

def _clean_json_string(text: str) -> str:
    # Remove leading/trailing code fences.
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    # Extract the JSON object from any extra text.
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]
    # Escape newline characters that are not already escaped.
    text = re.sub(r'(?<!\\)\n', '\\n', text)
    return text


async def generate_object(
    *,
    model: Callable[..., Awaitable[Any]],
    prompt: str,
    system: Optional[str] = None,
    schema: Optional[Any] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Generates a structured object from a given prompt using the provided language model (async).
    Mirroring the TS approach, we expect valid JSON.
    """
    final_prompt = f"{system}\n{prompt}" if system else prompt
    response = await model(final_prompt, **kwargs)

    try:
        text_output = response.choices[0].message.content
    except (AttributeError, IndexError) as e:
        try:
            text_output = response["choices"][0]["message"]["content"]
        except (AttributeError, IndexError) as err:
            raise ValueError(f"Failed to extract text from model response: {err}\nResponse: {response}")

    # Clean up common JSON formatting issues before parsing
    text_output = _clean_json_string(text_output)

    # No bullet or digit fallback; we rely on the model returning valid JSON.
    try:
        parsed_object = json.loads(text_output)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse model response as JSON: {e}\nResponse text: {text_output}"
        )

    # If a schema is provided, parse or transform
    if schema:
        if hasattr(schema, "parse_obj"):
            parsed_object = schema.parse_obj(parsed_object)
        else:
            parsed_object = schema(parsed_object)

    return {"object": parsed_object, "raw": response}
