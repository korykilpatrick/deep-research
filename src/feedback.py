from ai.ai import generate_object
from prompt import system_prompt
from ai.providers import ModelInfo, get_model
from pydantic import BaseModel
from typing import List, Optional

class FeedbackSchema(BaseModel):
    questions: List[str]

async def generate_feedback(query: str, num_questions: int = 5, model_info: Optional[ModelInfo] = None) -> List[str]:
    # Added explicit instruction: "Return your result in JSON..."
    prompt_text = (
        f"Given the following query from the user, ask some follow up questions to clarify the research direction.\n\n"
        f"Return your result in JSON format with the shape:\n"
        f'{{ "questions": [ "question1", "question2" ] }}\n\n'
        f"Return a maximum of {num_questions} questions, but feel free to return fewer if the original query is clear. Do not ask a question if you feel more than 80% confident that you already know the answer\n"
        f"<query>{query}</query>"
    )

    result = await generate_object(
        model=get_model(model_info),
        system=system_prompt(),
        prompt=prompt_text,
        schema=FeedbackSchema
    )
    return result["object"].questions[:num_questions]
