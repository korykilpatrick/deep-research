import asyncio
import uuid
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Any
import traceback

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from deep_research import deep_research, write_final_report
from ai.providers import ModelInfo
from feedback import generate_feedback
from output_manager import OutputManager
from docs import router as docs_router

app = FastAPI(title="Deep Research API")

# Include the docs router
app.include_router(docs_router)

# In-memory cache for storing research sessions
sessions = defaultdict(dict)

class ResearchRequest(BaseModel):
    user_id: str
    prompt: str
    breadth: Optional[int] = 4
    depth: Optional[int] = 2
    model: Optional[str] = None # e.g. "o3-mini", "chatgpt-4o-latest", "gpt-4o-mini"
    model_params: Optional[Dict] = None

class AnswerRequest(BaseModel):
    user_id: str
    job_id: str
    answers: List[str]

class Session:
    def __init__(self, prompt: str, breadth: int, depth: int, model_info: Optional[ModelInfo] = None):
        self.prompt = prompt
        self.breadth = breadth
        self.depth = depth
        self._follow_up_questions: List[str] = []
        self._answers: List[str] = []
        self.status = "pending_answers"  # pending_answers, running, completed, cancelled, failed
        self.result: Optional[Dict[str, Any]] = None
        self.created_at = datetime.now()
        self.model_info = model_info or ModelInfo()
        self.task = None

    @property
    def follow_up_questions(self):
        return self._follow_up_questions

    @follow_up_questions.setter
    def follow_up_questions(self, value):
        self._follow_up_questions = value
        self.status = "pending_answers"

    @property
    def answers(self):
        return self._answers

    @answers.setter
    def answers(self, value):
        self._answers = value
        self.status = "running"
    

    async def start_research(self):
        try:
            self.status = "running"
            output = OutputManager(verbose=True)
            # output = None
            
            # Combine initial prompt with follow-up answers
            combined_prompt = (
                f"Initial Prompt: {self.prompt}\n"
                "Follow-up Questions and Answers:\n" +
                "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(self.follow_up_questions, self.answers))
            )
            
            # Start the research process
            result = await deep_research(
                query=combined_prompt,
                breadth=self.breadth,
                depth=self.depth,
                model_info=self.model_info,
                on_progress=None
            )
            
            # Extract learnings and visited URLs
            learnings = result.get("learnings", [])
            visited_urls = result.get("visited_urls", [])
            
            # Debug - print what was returned
            output.debug(f"Result from deep_research: {result}")
            output.debug(f"Visited URLs count: {len(visited_urls)}")
            output.debug(f"First URL if available: {visited_urls[0] if visited_urls else 'None'}")
            
            # Generate the final report
            report = await write_final_report(
                prompt=combined_prompt,
                learnings=learnings,
                visited_urls=[],
                model_info=self.model_info
            )
            
            # Log final URL count before setting result
            output.debug(f"Final visited_urls count before setting result: {len(visited_urls)}")
            if visited_urls:
                output.debug(f"Example URL item: {visited_urls[0]}")
            
            # Update session with complete results
            self.result = {
                "prompt": combined_prompt,
                "report": report,
                "sources": visited_urls
            }
            self.status = "completed"
        except:
            traceback.print_exc()
            self.status = "failed"

def get_url(item):
    return (
            item.get("url") or
            item.get("metadata", {}).get("sourceURL") or
            item.get("metadata", {}).get("pageUrl") or
            item.get("metadata", {}).get("finalUrl") or
            item.get("metadata", {}).get("url")
        )

def cleanup_old_sessions():
    """Remove sessions older than 4 hours"""
    now = datetime.now()
    for user_id, user_sessions in sessions.items():
        expired_ids = [
            job_id for job_id, session in user_sessions.items()
            if now - session.created_at > timedelta(hours=4)
        ]
        for job_id in expired_ids:
            if user_sessions[job_id].task and not user_sessions[job_id].task.done():
                user_sessions[job_id].task.cancel()
            del user_sessions[job_id]

@app.post("/research/start")
async def start_research(request: ResearchRequest):
    """Initialize a research session with an initial prompt"""
    # Clean up old sessions
    cleanup_old_sessions()
    
    # Create a new session
    job_id = str(uuid.uuid4())
    model_info = ModelInfo(request.model, request.model_params)
    print(model_info.model, model_info.model_params)
    session = Session(request.prompt, request.breadth, request.depth, model_info)
    
    # Generate follow-up questions
    follow_up_questions = await generate_feedback(query=request.prompt, model_info=model_info)
    session.follow_up_questions = follow_up_questions
    
    # Store the session
    sessions[request.user_id][job_id] = session
    
    return {
        "job_id": job_id,
        "status": session.status,
        "questions": follow_up_questions
    }

@app.post("/research/answer")
async def provide_answers(request: AnswerRequest):
    """Provide answers to follow-up questions and start the research process"""
    if request.user_id not in sessions:
        raise HTTPException(status_code=404, detail="No user sessions found")
    elif request.job_id not in sessions[request.user_id]:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[request.user_id][request.job_id]
    
    if session.status != "pending_answers":
        raise HTTPException(status_code=400, detail="Session is not waiting for answers")
    
    if len(request.answers) != len(session.follow_up_questions):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(session.follow_up_questions)} answers, got {len(request.answers)}"
        )
    
    # Save the answers
    session.answers = request.answers
    
    # Start the research process as a background task
    task = asyncio.create_task(session.start_research())
    session.task = task
    
    return {"status": "running"}

@app.get("/research/status")
async def get_research_status(user_id: str, job_id: str):
    """Check the status of a research session"""
    if user_id not in sessions:
        raise HTTPException(status_code=404, detail="No user sessions found")
    if job_id not in sessions[user_id]:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[user_id][job_id]
    
    if session.status == "completed":
        return {
            "status": "completed",
            "results": session.result
        }
    else:
        return {"status": session.status}

@app.get("/research/cancel")
async def cancel_research_status(user_id: str, job_id: str):
    """Cancel a research session"""
    if user_id not in sessions:
        raise HTTPException(status_code=404, detail="No user sessions found")
    if job_id not in sessions[user_id]:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[user_id][job_id]
    
    if session.status == "completed":
        raise HTTPException(status_code=418, detail="Session already complete")
    else:
        if session.task:
            session.task.cancel()
        session.status = "cancelled"
        return {"status": session.status}

@app.get("/research/list")
async def get_research_sessions(user_id: str):
    """List recent research sessions for a user"""
    if user_id not in sessions:
        user_sessions = {}
    else:
        user_sessions = sessions[user_id]
    
    return {"sessions": [{"job_id": job_id, "status": user_sessions[job_id]["status"]} for job_id in user_sessions]}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)