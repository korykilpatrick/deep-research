import asyncio
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ai.ai import generate_object
from ai.providers import ModelInfo, get_model, trim_prompt, firecrawl_search
from prompt import system_prompt
from output_manager import OutputManager
from pydantic import BaseModel

# Use a single shared OutputManager if you like, or have run.py pass in an instance.
output = OutputManager()

def get_url(item):
    return (
            item.get("url") or
            item.get("metadata", {}).get("sourceURL") or
            item.get("metadata", {}).get("pageUrl") or
            item.get("metadata", {}).get("finalUrl") or
            item.get("metadata", {}).get("url")
        )

@dataclass
class ResearchProgress:
    current_depth: int
    total_depth: int
    current_breadth: int
    total_breadth: int
    current_query: Optional[str] = None
    total_queries: int = 0
    completed_queries: int = 0

class SerpQuery(BaseModel):
    query: str
    researchGoal: str

class SerpQueriesSchema(BaseModel):
    queries: List[SerpQuery]

class SerpResultSchema(BaseModel):
    learnings: List[str]
    followUpQuestions: List[str]

class FinalReportSchema(BaseModel):
    reportMarkdown: str

CONCURRENCY_LIMIT = int(os.getenv("CONCURRENCY_LIMIT", 2))

async def generate_serp_queries(
    query: str,
    learnings: Optional[List[str]] = None,
    num_queries: int = 3,
    model_info: Optional[ModelInfo] = None
) -> List[Dict[str, Any]]:
    extra = ""
    if learnings:
        extra = (
            "Here are some learnings from previous research. "
            "Use them to generate more specific queries:\n"
            + "\n".join(learnings)
        )

    prompt_text = (
        f"Given the following prompt from the user, generate a list of SERP queries to research the topic.\n\n"
        f"Return your result in JSON format with the shape:\n"
        f'{{ "queries": [ {{ "query": "string", "researchGoal": "string" }} ] }}\n\n'
        f"Return a maximum of {num_queries} queries, but feel free to return less if the original prompt is clear.\n"
        f"Make sure each query is unique and not similar to each other.\n\n"
        f"<prompt>{query}</prompt>\n\n{extra}"
    )

    res = await generate_object(
        model=get_model(model_info),
        system=system_prompt(),
        prompt=prompt_text,
        schema=SerpQueriesSchema
    )
    output.debug(f"Created {len(res['object'].queries)} queries", res["object"].queries)
    return res["object"].queries[:num_queries]

async def process_serp_result(
    query: str,
    result: Dict[str, Any],
    num_learnings: int = 3,
    num_follow_up_questions: int = 3,
    model_info: Optional[ModelInfo] = None
) -> Any:
    contents = []
    for item in result.get("data", []):
        if "markdown" in item:
            contents.append(trim_prompt(item["markdown"], 25000))

    output.debug(f"Ran {query}, found {len(contents)} contents")

    contents_wrapped = "\n".join(f"<content>\n{c}\n</content>" for c in contents)
    prompt_text = (
        f"Given the following contents from a SERP search for <query>{query}</query>, generate a list of learnings.\n"
        f"Return your result in JSON format with the shape:\n"
        f'{{ "learnings": ["..."], "followUpQuestions": ["..."] }}\n\n'
        f"Return a maximum of {num_learnings} learnings, but feel free to return less if the contents are clear.\n"
        f"Make sure each learning is unique and not similar to each other, including any relevant entities or numbers.\n\n"
        f"<contents>{contents_wrapped}</contents>"
    )

    res = await generate_object(
        model=get_model(model_info),
        system=system_prompt(),
        prompt=prompt_text,
        schema=SerpResultSchema
    )
    output.debug(f"Created {len(res['object'].learnings)} learnings", res["object"].learnings)
    return res["object"]

async def deep_research(
    query: str,
    breadth: int,
    depth: int,
    model_info: Optional[ModelInfo] = None,
    learnings: Optional[List[str]] = None,
    visited_urls: Optional[List[Dict]] = None,
    on_progress: Optional[Callable[[ResearchProgress], None]] = None
) -> Dict[str, Any]:
    if learnings is None:
        learnings = []
    if visited_urls is None:
        visited_urls = []

    progress = ResearchProgress(
        current_depth=depth,
        total_depth=depth,
        current_breadth=breadth,
        total_breadth=breadth,
        total_queries=0,
        completed_queries=0
    )

    def report_progress(update: Dict[str, Any]) -> None:
        for k, v in update.items():
            setattr(progress, k, v)
        if on_progress:
            on_progress(progress)

    serp_queries = await generate_serp_queries(query, learnings, num_queries=breadth, model_info=model_info)
    report_progress({
        "total_queries": len(serp_queries),
        "current_query": serp_queries[0].query if serp_queries else None
    })

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def process_query(serpQ: SerpQuery) -> Dict[str, Any]:
        async with sem:
            try:
                output.debug(f"Processing SERP query: {serpQ}")
                result = await loop.run_in_executor(
                    None,
                    lambda: firecrawl_search(
                        serpQ.query,
                        timeout=15000,
                        limit=5,
                    )
                )
                output.debug(f"Search results received for query '{serpQ.query}': {result}")
                if not result.get("data"):
                    output.debug(f"No results found for query: {serpQ.query}")
                    # Return already collected URLs instead of empty list
                    return {"learnings": learnings, "visited_urls": visited_urls}

                new_learnings_obj = await process_serp_result(
                    serpQ.query,
                    result,
                    num_learnings=breadth // 2,
                    num_follow_up_questions=breadth // 2,
                    model_info=model_info
                )
                new_urls = []
                for item in result.get("data", []):
                    if get_url(item):
                        new_urls.append(item)
                
                output.debug(f"Found {len(new_urls)} new URLs for query: {serpQ.query}")
                output.debug(f"First new URL item: {new_urls[0] if new_urls else 'None'}")

                all_learnings = learnings + new_learnings_obj.learnings
                all_urls = visited_urls + new_urls
                output.debug(f"Total URLs after adding new ones: {len(all_urls)}")
                new_depth = depth - 1
                if new_depth > 0:
                    output.debug(f"Researching deeper, breadth: {breadth // 2}, depth: {new_depth}")
                    report_progress({
                        "current_depth": new_depth,
                        "current_breadth": breadth // 2,
                        "completed_queries": progress.completed_queries + 1,
                        "current_query": serpQ.query,
                    })
                    next_query = (
                        f"Previous research goal: {serpQ.researchGoal}\n"
                        f"Follow-up research directions: {chr(10).join(new_learnings_obj.followUpQuestions)}"
                    ).strip()
                    return await deep_research(
                        query=next_query,
                        breadth=breadth // 2,
                        depth=new_depth,
                        model_info=model_info,
                        learnings=all_learnings,
                        visited_urls=all_urls,
                        on_progress=on_progress
                    )
                else:
                    report_progress({
                        "current_depth": 0,
                        "completed_queries": progress.completed_queries + 1,
                        "current_query": serpQ.query,
                    })
                    return {"learnings": all_learnings, "visited_urls": all_urls}
            except Exception as e:
                output.debug(f"Error running query: {serpQ.query}: {e}")
                # Return already collected URLs instead of empty list
                return {"learnings": learnings, "visited_urls": visited_urls}

    tasks = [process_query(q) for q in serp_queries]
    results = await asyncio.gather(*tasks)

    # Use a list comprehension for learnings to remove duplicates (they're strings)
    final_learnings = list({l for r in results for l in r["learnings"]})
    
    # For URLs, don't use a set as it might lose information due to dictionary equality
    # Instead, keep track of seen URLs by their actual URL string to avoid duplicates
    seen_urls = set()
    final_urls = []
    for result in results:
        for url_item in result.get("visited_urls", []):
            url_string = get_url(url_item)
            if url_string and url_string not in seen_urls:
                seen_urls.add(url_string)
                final_urls.append(url_item)
    
    output.debug(f"deep_research final URLs count: {len(final_urls)}")
    output.debug(f"deep_research first URL item: {final_urls[0] if final_urls else 'None'}")
    
    return {"learnings": final_learnings, "visited_urls": final_urls}

async def write_final_report(
    prompt: str,
    learnings: List[str],
    visited_urls: List[Dict],
    model_info: Optional[ModelInfo] = None
) -> str:
    learnings_wrapped = "\n".join(f"<learning>\n{l}\n</learning>" for l in learnings)
    trimmed_learnings = trim_prompt(learnings_wrapped, 150_000)
    full_prompt = (
        f"Given the following prompt from the user, write a final report on the topic using the learnings from research. "
        f"Make it as detailed as possible, aim for 3 or more pages, and include ALL the learnings from research. "
        f"Return your result in JSON format with the following structure:\n"
        f'{{ "reportMarkdown": <your report markdown> }}.\n\n'
        f"<prompt>{prompt}</prompt>\n\n"
        f"Here are all the learnings from previous research:\n\n"
        f"<learnings>\n{trimmed_learnings}\n</learnings>"
    )
    res = await generate_object(
        model=get_model(model_info),
        system=system_prompt(),
        prompt=full_prompt,
        schema=FinalReportSchema
    )
    report = res["object"].reportMarkdown
    if visited_urls:
        sources_section = "\n\n## Sources\n\n" + "\n".join(f"- {get_url(u)}" for u in visited_urls)
    else:
        sources_section = ""
    return report + sources_section
