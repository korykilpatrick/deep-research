from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import os
import pathlib

# Create router
router = APIRouter()

# HTML content as a constant to be used if Jinja2 is not installed
API_DOCS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deep Research API Documentation</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        h1, h2, h3 {
            color: #2c3e50;
        }
        pre {
            background-color: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
        code {
            font-family: 'Courier New', Courier, monospace;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
        }
        .endpoint {
            border-left: 4px solid #3498db;
            padding-left: 15px;
            margin: 30px 0;
        }
        .method {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 5px;
            font-weight: bold;
            margin-right: 10px;
        }
        .get {
            background-color: #61affe;
            color: white;
        }
        .post {
            background-color: #49cc90;
            color: white;
        }
    </style>
</head>
<body>
    <h1>Deep Research API Documentation</h1>
    
    <p>This API provides access to the Deep Research functionality, allowing you to perform iterative research on any topic using web scraping and LLM-driven query generation.</p>
    
    <h2>API Endpoints</h2>

    <div class="endpoint">
        <h3><span class="method post">POST</span>/research/start</h3>
        <p>Initialize a research session with an initial prompt.</p>
        
        <h4>Request Body</h4>
        <pre><code>{
  "user_id": "string",          // Required: Unique identifier for the user
  "prompt": "string",           // Required: Your research topic
  "breadth": 4,                 // Optional: Number of search queries per iteration (default: 4)
  "depth": 2,                   // Optional: Number of recursive exploration iterations (default: 2)
  "model": "string",            // Optional: LLM model to use (e.g., "o3-mini", "chatgpt-4o-latest")
  "model_params": {}            // Optional: Additional parameters for the LLM
}</code></pre>
        
        <h4>Response</h4>
        <pre><code>{
  "job_id": "unique-uuid",        // Unique identifier for this research session
  "status": "pending_answers",     // Current status of the research session
  "questions": [                  // Follow-up questions to refine research direction
    "Question 1", 
    "Question 2", 
    "Question 3"
  ]
}</code></pre>
    </div>

    <div class="endpoint">
        <h3><span class="method post">POST</span>/research/answer</h3>
        <p>Provide answers to follow-up questions and start the research process.</p>
        
        <h4>Request Body</h4>
        <pre><code>{
  "user_id": "string",          // Required: Unique identifier for the user
  "job_id": "string",           // Required: Unique identifier for the research session
  "answers": [                  // Required: Answers to the follow-up questions
    "Answer 1", 
    "Answer 2", 
    "Answer 3"
  ]
}</code></pre>
        
        <h4>Response</h4>
        <pre><code>{
  "status": "running"           // New status of the research session
}</code></pre>
    </div>

    <div class="endpoint">
        <h3><span class="method get">GET</span>/research/status</h3>
        <p>Check the status of a research session.</p>
        
        <h4>Query Parameters</h4>
        <table>
            <tr>
                <th>Parameter</th>
                <th>Type</th>
                <th>Description</th>
                <th>Required</th>
            </tr>
            <tr>
                <td>user_id</td>
                <td>string</td>
                <td>Unique identifier for the user</td>
                <td>Yes</td>
            </tr>
            <tr>
                <td>job_id</td>
                <td>string</td>
                <td>Unique identifier for the research session</td>
                <td>Yes</td>
            </tr>
        </table>
        
        <h4>Response (in progress)</h4>
        <pre><code>{
  "status": "running"           // Current status of the research
}</code></pre>
        
        <h4>Response (completed)</h4>
        <pre><code>{
  "status": "completed",
  "results": {
    "prompt": "Combined query with answers",
    "report": "Markdown report content",
    "sources": ["URL 1", "URL 2", "..."]
  }
}</code></pre>
    </div>

    <div class="endpoint">
        <h3><span class="method get">GET</span>/research/cancel</h3>
        <p>Cancel a running research session.</p>
        
        <h4>Query Parameters</h4>
        <table>
            <tr>
                <th>Parameter</th>
                <th>Type</th>
                <th>Description</th>
                <th>Required</th>
            </tr>
            <tr>
                <td>user_id</td>
                <td>string</td>
                <td>Unique identifier for the user</td>
                <td>Yes</td>
            </tr>
            <tr>
                <td>job_id</td>
                <td>string</td>
                <td>Unique identifier for the research session</td>
                <td>Yes</td>
            </tr>
        </table>
        
        <h4>Response</h4>
        <pre><code>{
  "status": "cancelled"         // New status of the research session
}</code></pre>
    </div>

    <div class="endpoint">
        <h3><span class="method get">GET</span>/research/list</h3>
        <p>List all recent research sessions for a user.</p>
        
        <h4>Query Parameters</h4>
        <table>
            <tr>
                <th>Parameter</th>
                <th>Type</th>
                <th>Description</th>
                <th>Required</th>
            </tr>
            <tr>
                <td>user_id</td>
                <td>string</td>
                <td>Unique identifier for the user</td>
                <td>Yes</td>
            </tr>
        </table>
        
        <h4>Response</h4>
        <pre><code>{
  "sessions": [
    {
      "job_id": "unique-uuid-1",
      "status": "completed"
    },
    {
      "job_id": "unique-uuid-2",
      "status": "running"
    }
  ]
}</code></pre>
    </div>

    <h2>Status Values</h2>
    <p>A research session can have the following status values:</p>
    <ul>
        <li><strong>pending_answers</strong>: Waiting for answers to follow-up questions</li>
        <li><strong>running</strong>: Research is in progress</li>
        <li><strong>completed</strong>: Research is complete and results are available</li>
        <li><strong>cancelled</strong>: Research was cancelled by the user</li>
        <li><strong>failed</strong>: Research encountered an error</li>
    </ul>
    
    <h2>Notes</h2>
    <ul>
        <li>Research sessions are cached for 4 hours before being automatically removed.</li>
        <li>When using custom models, make sure they are available in your OpenAI/Anthropic API account.</li>
    </ul>
</body>
</html>
"""

try:
    from fastapi.templating import Jinja2Templates
    
    # Create templates directory if it doesn't exist
    templates_dir = pathlib.Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    
    # Create Jinja2Templates instance
    templates = Jinja2Templates(directory=str(templates_dir))
    
    # Create the HTML template file if it doesn't exist
    template_path = templates_dir / "api_docs.html"
    if not template_path.exists():
        with open(template_path, "w") as f:
            f.write(API_DOCS_HTML)
    
    @router.get("/docs/api", response_class=HTMLResponse)
    async def api_docs(request: Request):
        """Serve the API documentation page using Jinja2 templates"""
        return templates.TemplateResponse("api_docs.html", {"request": request})
    
except ImportError:
    # Fallback if Jinja2 is not installed
    @router.get("/docs/api", response_class=HTMLResponse)
    async def api_docs():
        """Serve the API documentation page as a simple HTML response"""
        return HTMLResponse(content=API_DOCS_HTML) 