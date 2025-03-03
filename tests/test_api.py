import os
import requests
import sys
import time
import json
import argparse
import traceback
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table

FILE_PATH = os.path.dirname(os.path.abspath(__file__))

# Initialize rich console for better output
console = Console()

def load_config():
    """Load configuration from environment variables with defaults"""
    load_dotenv(override=True)
    
    config = {
        "api_scheme": os.getenv("API_SCHEME", "http"),
        "api_host": os.getenv("API_HOST", "localhost"),
        "api_port": os.getenv("API_PORT", 8001),
        "user_id": os.getenv("USER_ID", "123456"),
    }
    
    config["base_url"] = f'{config["api_scheme"]}://{config["api_host"]}:{config["api_port"]}/research'
    return config

def start_research(config, args):
    """Start a new research job"""
    # Use args.prompt if provided, otherwise prompt interactively
    prompt = args.prompt
    if not prompt:
        prompt = console.input("[bold cyan]Enter your research prompt:[/] ")
    
    model_params = json.loads(args.params) if args.params else {"temperature": args.temperature}
    data = {
        "user_id": config["user_id"],
        "prompt": prompt,
        "depth": args.depth,
        "breadth": args.breadth,
        "model": args.model,
        "model_params": model_params
    }

    with console.status("[bold green]Starting research job..."):
        try:
            res = requests.post(f'{config["base_url"]}/start', json=data)
            res.raise_for_status()
            result = res.json()
            console.print(f"[bold green]Successfully started research job:[/] [bold]{result['job_id']}[/]")
            return result
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error starting research:[/] {str(e)}")
            sys.exit(1)

def answer_questions(config, job_id, questions=None, answers_file=None):
    """Answer questions for a research job"""
    if not questions:
        # Get the questions first
        with console.status("[bold green]Fetching questions..."):
            try:
                res = requests.get(f'{config["base_url"]}/status?user_id={config["user_id"]}&job_id={job_id}')
                res.raise_for_status()
                status_data = res.json()
                questions = status_data.get('questions', [])
            except requests.exceptions.RequestException as e:
                console.print(f"[bold red]Error fetching questions:[/] {str(e)}")
                sys.exit(1)
    
    # If no questions, report this
    if not questions:
        console.print("[yellow]No questions to answer.[/]")
        return {"user_id": config["user_id"], "job_id": job_id, "answers": []}
    
    # If answers_file is provided, load answers from it
    answers = []
    if answers_file:
        try:
            with open(answers_file, 'r') as f:
                answers = json.load(f)
            if len(answers) != len(questions):
                console.print(f"[bold red]Error:[/] Answer file contains {len(answers)} answers but there are {len(questions)} questions.")
                sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]Error loading answers file:[/] {str(e)}")
            sys.exit(1)
    else:
        # Interactive mode
        console.print("[bold cyan]Please answer the following questions:[/]")
        for i, q in enumerate(questions):
            console.print(f"\n[bold]{i+1}/{len(questions)}[/]: {q}")
            answer = console.input("[bold cyan]Your answer:[/] ")
            answers.append(answer)
    
    # Submit answers
    data = {"user_id": config["user_id"], "job_id": job_id, "answers": answers}
    with console.status("[bold green]Submitting answers..."):
        try:
            res = requests.post(f'{config["base_url"]}/answer', json=data)
            res.raise_for_status()
            result = res.json()
            console.print("[bold green]Answers submitted successfully.[/]")
            return result
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error submitting answers:[/] {str(e)}")
            sys.exit(1)

def check_status(config, job_id, wait=False, interval=30):
    """Check the status of a research job"""
    if wait:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Waiting for research to complete..."),
            console=console
        ) as progress:
            task = progress.add_task("Waiting", total=None)
            
            while True:
                try:
                    res = requests.get(f'{config["base_url"]}/status?user_id={config["user_id"]}&job_id={job_id}')
                    res.raise_for_status()
                    status_data = res.json()
                    
                    status = status_data.get('status')
                    if status in ("completed", "failed"):
                        break
                    
                    progress.update(task, description=f"[bold green]Status: {status} - Checking again in {interval} seconds...")
                    time.sleep(interval)
                except KeyboardInterrupt:
                    console.print("\n[yellow]Operation cancelled by user.[/]")
                    sys.exit(0)
                except Exception as e:
                    console.print(f"\n[bold red]Error checking status:[/] {str(e)}")
                    time.sleep(interval)  # Still wait before retrying
    else:
        # Just check once
        with console.status("[bold green]Checking job status..."):
            try:
                res = requests.get(f'{config["base_url"]}/status?user_id={config["user_id"]}&job_id={job_id}')
                res.raise_for_status()
                status_data = res.json()
                return status_data
            except requests.exceptions.RequestException as e:
                console.print(f"[bold red]Error checking status:[/] {str(e)}")
                sys.exit(1)
    
    return status_data

def display_results(results):
    """Display research results in a visually appealing format"""
    if not results:
        console.print("[yellow]No results to display.[/]")
        return
    
    # Display the prompt
    if "prompt" in results:
        console.print(Panel(results["prompt"], title="Research Prompt", border_style="cyan"))
    
    # Display the report
    if "report" in results:
        console.print(Panel(results["report"], title="Research Report", border_style="green"))
    
    # Display sources if available
    if "sources" in results and results["sources"]:
        table = Table(title="Sources")
        table.add_column("Title", style="cyan")
        table.add_column("URL", style="blue")
        table.add_column("Description", style="green")
        
        for source in results["sources"]:
            title = source.get("title", "N/A")
            url = source.get("url", "N/A")
            description = source.get("description", "N/A")
            table.add_row(title, url, description)
        
        console.print(table)
    
    # Save to file option
    save = console.input("[bold cyan]Save results to file? (y/n):[/] ").lower()
    if save == 'y':
        filename = console.input("[bold cyan]Enter filename:[/] ") or os.path.join(FILE_PATH, os.path.pardir, os.sep, "research_results.json")
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        console.print(f"[bold green]Results saved to {filename}[/]")

def main():
    """Main entry point for the CLI"""
    config = load_config()
    
    parser = argparse.ArgumentParser(description="Deep Research API Client")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Start research command
    start_parser = subparsers.add_parser("start", help="Start a new research job")
    start_parser.add_argument("--prompt", "-p", help="Research prompt")
    start_parser.add_argument("--depth", "-d", type=int, default=2, help="Research depth (default: 2)")
    start_parser.add_argument("--breadth", "-b", type=int, default=2, help="Research breadth (default: 2)")
    start_parser.add_argument("--model", "-m", default="gpt-4o-mini", help="Model to use (default: gpt-4o-mini)")
    start_parser.add_argument("--temperature", "-t", type=float, default=0.3, help="Model temperature (default: 0.3)")
    start_parser.add_argument("--params", type=str, help="Model params (JSON format)")
    start_parser.add_argument("--continue", "-c", dest="continue_flow", action="store_true", help="Continue with answering questions and monitoring")
    
    # Answer command
    answer_parser = subparsers.add_parser("answer", help="Answer questions for a research job")
    answer_parser.add_argument("job_id", help="ID of the research job")
    answer_parser.add_argument("--file", "-f", dest="answers_file", help="JSON file containing answers")
    answer_parser.add_argument("--continue", "-c", dest="continue_flow", action="store_true", help="Continue with monitoring after answering")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Check the status of a research job")
    status_parser.add_argument("job_id", help="ID of the research job")
    status_parser.add_argument("--wait", "-w", action="store_true", help="Wait for job to complete")
    status_parser.add_argument("--interval", "-i", type=int, default=30, help="Check interval in seconds (default: 30)")
    
    # Results command
    results_parser = subparsers.add_parser("results", help="Display results of a completed research job")
    results_parser.add_argument("job_id", help="ID of the research job")
    
    # Full flow command
    flow_parser = subparsers.add_parser("flow", help="Run the complete research flow")
    flow_parser.add_argument("--prompt", "-p", help="Research prompt")
    flow_parser.add_argument("--depth", "-d", type=int, default=2, help="Research depth (default: 2)")
    flow_parser.add_argument("--breadth", "-b", type=int, default=2, help="Research breadth (default: 2)")
    flow_parser.add_argument("--model", "-m", default="gpt-4o-mini", help="Model to use (default: gpt-4o-mini)")
    flow_parser.add_argument("--temperature", "-t", type=float, default=0.3, help="Model temperature (default: 0.3)")
    flow_parser.add_argument("--interval", "-i", type=int, default=30, help="Status check interval in seconds (default: 30)")
    
    args = parser.parse_args()
    
    # If no command provided, default to 'flow'
    if not args.command:
        console.print("[dim]No command specified. Running full research flow...[/]")
        # Create a new namespace with default arguments for flow
        default_args = argparse.Namespace(
            command="flow",
            prompt=None,
            depth=2,
            breadth=2,
            model="gpt-4o-mini",
            temperature=0.3,
            interval=30
        )
        args = default_args
    
    # Execute the appropriate command
    if args.command == "start":
        result = start_research(config, args)
        if args.continue_flow:
            # Continue with answers
            answer_result = answer_questions(config, result['job_id'], result.get('questions'))
            # Continue with status monitoring
            status_result = check_status(config, result['job_id'], wait=True, interval=30)
            if status_result.get('status') == "completed":
                display_results(status_result.get('results', {}))
            else:
                console.print(f"[bold red]Research job is not complete. Current status: {status_result.get('status', 'unknown')}[/]")
        else:
            console.print(f"Job ID: {result['job_id']}")
            if 'questions' in result:
                console.print("\n[bold cyan]Questions to answer:[/]")
                for i, q in enumerate(result['questions']):
                    console.print(f"{i+1}. {q}")
    
    elif args.command == "answer":
        result = answer_questions(config, args.job_id, answers_file=args.answers_file)
        if args.continue_flow:
            status_result = check_status(config, args.job_id, wait=True, interval=30)
            if status_result.get('status') == "completed":
                display_results(status_result.get('results', {}))
    
    elif args.command == "status":
        result = check_status(config, args.job_id, wait=args.wait, interval=args.interval)
        
        # Display the result
        status = result.get('status', 'unknown')
        console.print(f"[bold]Status:[/] {status}")
        
        if status == "completed":
            display_results(result.get('results', {}))
        elif 'questions' in result and result['questions']:
            console.print("\n[bold cyan]Questions to answer:[/]")
            for i, q in enumerate(result['questions']):
                console.print(f"{i+1}. {q}")
    
    elif args.command == "results":
        result = check_status(config, args.job_id)
        if result.get('status') == "completed":
            display_results(result.get('results', {}))
        else:
            console.print(f"[yellow]Research job is not complete. Current status: {result.get('status', 'unknown')}[/]")
    
    elif args.command == "flow":
        # Complete flow: start -> answer -> wait -> display results
        start_result = start_research(config, args)
        answer_result = answer_questions(config, start_result['job_id'], start_result.get('questions'))
        status_result = check_status(config, start_result['job_id'], wait=True, interval=args.interval)
        if status_result.get('status') == "completed":
            display_results(status_result.get('results', {}))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {str(e)}")
        console.print("[dim]For full traceback, run with --debug[/]")
        sys.exit(1)
