import asyncio
import sys

from cli_style import ask_user, show_header
from deep_research import deep_research, write_final_report
from feedback import generate_feedback
from output_manager import OutputManager

def print_help_and_exit():
    usage = (
        "Usage:\n"
        "  python src/run.py [--verbose] [--help]\n\n"
        "Options:\n"
        "  --verbose     Show debug logs\n"
        "  --help        Show this help message\n"
    )
    print(usage)
    sys.exit(1)

def get_url(item):
    return (
            item.get("url") or
            item.get("metadata", {}).get("sourceURL") or
            item.get("metadata", {}).get("pageUrl") or
            item.get("metadata", {}).get("finalUrl") or
            item.get("metadata", {}).get("url")
        )

async def run():
    # Allowed arguments
    allowed_args = {"--verbose", "--help"}

    # Identify invalid flags (any that aren't allowed)
    user_args = set(sys.argv[1:])
    invalid = [arg for arg in user_args if arg not in allowed_args]
    if invalid:
        # unknown arg, show usage and exit
        print_help_and_exit()

    # If the user asked for help, show usage and exit
    if "--help" in user_args:
        print_help_and_exit()

    # Check if --verbose is in command arguments
    verbose_mode = "--verbose" in user_args

    # Create an OutputManager instance with the desired verbosity
    output = OutputManager(verbose=verbose_mode)

    show_header("Deep Research")

    # Start user interaction
    initial_query = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: ask_user("What would you like to research?")
    )

    # Depth / breadth questions are user interactions; always display
    try:
        breadth_input = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: ask_user("Enter research breadth (recommended 2-10, default 4)")
        )
        breadth = int(breadth_input)
    except ValueError:
        breadth = 4

    try:
        depth_input = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: ask_user("Enter research depth (recommended 1-5, default 2)")
        )
        depth = int(depth_input)
    except ValueError:
        depth = 2

    output.debug("Creating research plan...")

    follow_up_questions = await generate_feedback(query=initial_query)
    output.info("\nTo better understand your research needs, please answer these follow-up questions:")

    answers = []
    for question in follow_up_questions:
        answer = await asyncio.get_running_loop().run_in_executor(None, lambda: ask_user(question))
        answers.append(answer)

    combined_query = (
        f"Initial Query: {initial_query}\n"
        "Follow-up Questions and Answers:\n" +
        "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(follow_up_questions, answers))
    )

    output.debug("Researching your topic...")
    output.debug("Starting research with progress tracking...")

    result = await deep_research(
        query=combined_query,
        breadth=breadth,
        depth=depth,
        on_progress=output.update_progress
    )
    output.stop_progress()

    learnings = result.get("learnings", [])
    visited_urls = result.get("visited_urls", [])

    output.debug(f"\nLearnings:\n{chr(10).join(learnings)}")
    output.debug(f"\nVisited URLs ({len(visited_urls)}):\n{chr(10).join([get_url(u) for u in visited_urls])}")
    output.debug("Writing final report...")

    report = await write_final_report(
        prompt=combined_query,
        learnings=learnings,
        visited_urls=visited_urls
    )

    output.debug("\nFinal Report:\n")
    output.debug(report)

    # Final user-facing message
    output.info("\nReport has been saved to output.md")

    with open("output.md", "w", encoding="utf-8") as f:
        f.write(report)

if __name__ == "__main__":
    asyncio.run(run())
