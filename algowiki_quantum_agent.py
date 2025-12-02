#!/usr/bin/env python3
"""
AlgoWiki Quantum Algorithm Research Agent

This agent:
1. Takes a problem number (e.g., 1 for Sorting) from the user
2. Looks up all subproblems under that number from the "Problems" sheet
3. Searches arXiv for quantum algorithms addressing each subproblem
4. Adds new entries to the "Quantum Algorithms" sheet in Google Sheets
"""

import os
import json
import re
from datetime import datetime
from typing import Optional
import anthropic
import arxiv
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# =============================================================================
# Configuration
# =============================================================================
MAX_AGENT_STEPS = 40

# Google service account credentials (standard Google format)
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"

# Secrets file for API keys (keeps them out of git)
SECRETS_FILE = "secrets.json"

SPREADSHEET_NAME = "AlgoWiki algorithms (our copy)"  # Your Google Sheet name

# Path to the local Excel file for reading problem structure
LOCAL_EXCEL_PATH = r"C:\Users\jyoum\Downloads\AlgoWiki algorithms (our copy).xlsx"

# =============================================================================
# API Key Loading
# =============================================================================
def get_api_key():
    """Load Anthropic API key from secrets.json file."""
    try:
        with open(SECRETS_FILE) as f:
            secrets = json.load(f)
        
        api_key = secrets.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(f"ANTHROPIC_API_KEY not found in {SECRETS_FILE}")
        return api_key
    
    except FileNotFoundError:
        print(f"\n❌ {SECRETS_FILE} not found!")
        print(f"\nCreate a file named '{SECRETS_FILE}' with this content:")
        print('{\n    "ANTHROPIC_API_KEY": "sk-ant-api03-your-key-here"\n}')
        raise

# =============================================================================
# Tool Definitions for the Agent
# =============================================================================
TOOLS = [
    {
        "name": "get_subproblems",
        "description": "Get all subproblems (variations) for a given problem number from the Problems sheet. Returns the family name and all variations under that problem number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "problem_number": {
                    "type": "integer",
                    "description": "The problem number from the Problems sheet (e.g., 1 for Sorting, 5 for Maximum Flow)"
                }
            },
            "required": ["problem_number"]
        }
    },
    {
        "name": "search_quantum_papers",
        "description": "Search arXiv for quantum algorithm papers related to a specific problem/subproblem. Returns up to 10 papers with metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "problem_name": {
                    "type": "string",
                    "description": "The name of the problem to search for (e.g., 'Sorting', 'Comparison Sorting', 'Maximum Flow')"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of papers to return (default 10)",
                    "default": 10
                }
            },
            "required": ["problem_name"]
        }
    },
    {
        "name": "get_existing_quantum_algorithms",
        "description": "Get existing quantum algorithm entries from the Quantum Algorithms sheet to check for duplicates. Returns paper titles and arXiv IDs already in the sheet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "problem_number": {
                    "type": "integer",
                    "description": "Optional: Filter by problem number. If not provided, returns all existing entries."
                }
            },
            "required": []
        }
    },
    {
        "name": "add_quantum_algorithm",
        "description": "Add a new quantum algorithm entry to the Quantum Algorithms sheet in Google Sheets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "problem_number": {
                    "type": "number",
                    "description": "The problem number (e.g., 1.0 for Sorting)"
                },
                "family_name": {
                    "type": "string",
                    "description": "The problem family name (e.g., 'Sorting', 'Linear System')"
                },
                "variation": {
                    "type": "string",
                    "description": "The specific variation/subproblem (e.g., 'Comparison Sorting', 'Quantum Sorting')"
                },
                "algorithm_name": {
                    "type": "string",
                    "description": "Name of the algorithm"
                },
                "year": {
                    "type": "integer",
                    "description": "Year of publication"
                },
                "paper_link": {
                    "type": "string",
                    "description": "URL to the paper (arXiv link preferred)"
                },
                "doi": {
                    "type": "string",
                    "description": "DOI of the paper if available"
                },
                "authors": {
                    "type": "string",
                    "description": "Authors of the paper (comma-separated or as a list string)"
                },
                "title": {
                    "type": "string",
                    "description": "Full title of the paper"
                },
                "time_complexity": {
                    "type": "string",
                    "description": "Time complexity or circuit depth (e.g., 'O(n log n)', 'O(sqrt(n))')"
                },
                "space_complexity": {
                    "type": "string",
                    "description": "Space/qubit complexity if mentioned"
                },
                "parameter_definitions": {
                    "type": "string",
                    "description": "Definition of parameters used (e.g., 'n: number of elements')"
                },
                "computational_model": {
                    "type": "string",
                    "description": "Computational model (e.g., 'Quantum Computer', 'Quantum Circuit')"
                },
                "algorithm_description": {
                    "type": "string",
                    "description": "Brief description of the algorithm"
                }
            },
            "required": ["problem_number", "family_name", "variation", "algorithm_name", 
                        "year", "paper_link", "authors", "title"]
        }
    },
    {
        "name": "finish",
        "description": "Call this when all research and updates are complete. Provide a summary of what was done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of the research completed and algorithms added"
                },
                "papers_found": {
                    "type": "integer",
                    "description": "Total number of relevant papers found"
                },
                "papers_added": {
                    "type": "integer",
                    "description": "Number of new papers added to the sheet"
                },
                "papers_skipped": {
                    "type": "integer",
                    "description": "Number of papers skipped (duplicates or not relevant)"
                }
            },
            "required": ["summary", "papers_found", "papers_added", "papers_skipped"]
        }
    }
]

# =============================================================================
# Google Sheets Setup
# =============================================================================
def get_google_sheets_client():
    """Initialize and return Google Sheets client."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)

def get_quantum_algorithms_sheet():
    """Get the Quantum Algorithms worksheet."""
    gc = get_google_sheets_client()
    spreadsheet = gc.open(SPREADSHEET_NAME)
    return spreadsheet.worksheet("Quantum Algorithms")

# =============================================================================
# Tool Implementation Functions
# =============================================================================
def get_subproblems(problem_number: int) -> dict:
    """
    Get all subproblems for a given problem number from the Problems sheet.
    Reads from the local Excel file.
    """
    try:
        df = pd.read_excel(LOCAL_EXCEL_PATH, sheet_name="Problems")
        
        # Filter by Old Family # (problem number)
        filtered = df[df['Old Family #'] == float(problem_number)]
        
        if filtered.empty:
            return {
                "success": False,
                "error": f"No problems found with number {problem_number}"
            }
        
        # Get family name and all variations
        family_name = filtered['Family Name'].iloc[0]
        variations = filtered['Variation'].dropna().tolist()
        
        # Also get aliases if they exist
        aliases = filtered['Alias'].dropna().tolist()
        
        # Get problem descriptions
        descriptions = []
        for _, row in filtered.iterrows():
            desc = {
                "variation": row['Variation'] if pd.notna(row['Variation']) else "General",
                "alias": row['Alias'] if pd.notna(row['Alias']) else None,
                "description": row['Problem Description'][:300] if pd.notna(row['Problem Description']) else None
            }
            descriptions.append(desc)
        
        return {
            "success": True,
            "problem_number": problem_number,
            "family_name": family_name,
            "variations": variations,
            "aliases": aliases,
            "subproblems": descriptions,
            "total_subproblems": len(descriptions)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_quantum_papers(problem_name: str, max_results: int = 10) -> dict:
    """
    Search arXiv for quantum algorithm papers related to a problem.
    """
    try:
        # Build search query - focus on quantum algorithms
        query = f'(ti:quantum OR abs:quantum) AND (ti:"{problem_name}" OR abs:"{problem_name}") AND (cat:quant-ph OR cat:cs.DS OR cat:cs.CC)'
        
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        papers = []
        for result in client.results(search):
            # Extract arXiv ID (remove version suffix for comparison)
            arxiv_id = result.entry_id.split("/")[-1]
            arxiv_id_base = re.sub(r'v\d+$', '', arxiv_id)
            
            # Extract year from published date
            year = result.published.year
            
            # Get DOI if available
            doi = result.doi if result.doi else None
            
            # Format authors
            authors = [author.name for author in result.authors]
            
            paper = {
                "arxiv_id": arxiv_id,
                "arxiv_id_base": arxiv_id_base,
                "title": result.title,
                "authors": authors,
                "year": year,
                "abstract": result.summary[:800],  # Truncate for context window
                "pdf_url": result.pdf_url,
                "entry_url": result.entry_id,
                "doi": doi,
                "categories": result.categories
            }
            papers.append(paper)
        
        return {
            "success": True,
            "query": query,
            "problem_searched": problem_name,
            "papers_found": len(papers),
            "papers": papers
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_existing_quantum_algorithms(problem_number: Optional[int] = None) -> dict:
    """
    Get existing quantum algorithm entries from the sheet.
    """
    try:
        sheet = get_quantum_algorithms_sheet()
        all_values = sheet.get_all_values()
        
        if len(all_values) < 2:
            return {
                "success": True,
                "existing_entries": [],
                "total_entries": 0
            }
        
        headers = all_values[0]
        rows = all_values[1:]
        
        # Find relevant column indices
        try:
            problem_num_idx = 0  # Usually first column (Unnamed: 0)
            title_idx = headers.index('Title') if 'Title' in headers else None
            link_idx = headers.index('Paper/Reference Link') if 'Paper/Reference Link' in headers else None
            family_idx = headers.index('Family Name') if 'Family Name' in headers else None
            variation_idx = headers.index('Variation') if 'Variation' in headers else None
        except ValueError:
            pass
        
        entries = []
        for row in rows:
            if len(row) > 0:
                entry = {
                    "problem_number": row[problem_num_idx] if problem_num_idx < len(row) else None,
                    "family_name": row[family_idx] if family_idx and family_idx < len(row) else None,
                    "variation": row[variation_idx] if variation_idx and variation_idx < len(row) else None,
                    "title": row[title_idx] if title_idx and title_idx < len(row) else None,
                    "paper_link": row[link_idx] if link_idx and link_idx < len(row) else None
                }
                
                # Filter by problem number if specified
                if problem_number is not None:
                    try:
                        entry_num = float(entry["problem_number"]) if entry["problem_number"] else None
                        if entry_num != float(problem_number):
                            continue
                    except (ValueError, TypeError):
                        continue
                
                # Only include entries with some data
                if entry["title"] or entry["paper_link"]:
                    entries.append(entry)
        
        # Extract arXiv IDs from links for duplicate checking
        existing_arxiv_ids = set()
        existing_titles = set()
        for entry in entries:
            if entry["paper_link"]:
                # Try to extract arXiv ID from link
                match = re.search(r'(\d{4}\.\d{4,5})', entry["paper_link"])
                if match:
                    existing_arxiv_ids.add(match.group(1))
            if entry["title"]:
                existing_titles.add(entry["title"].lower().strip())
        
        return {
            "success": True,
            "existing_entries": entries[:50],  # Limit to 50 for context
            "existing_arxiv_ids": list(existing_arxiv_ids),
            "existing_titles": list(existing_titles)[:50],
            "total_entries": len(entries)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def add_quantum_algorithm(
    problem_number: float,
    family_name: str,
    variation: str,
    algorithm_name: str,
    year: int,
    paper_link: str,
    authors: str,
    title: str,
    doi: str = None,
    time_complexity: str = None,
    space_complexity: str = None,
    parameter_definitions: str = None,
    computational_model: str = "Quantum Computer",
    algorithm_description: str = None
) -> dict:
    """
    Add a new quantum algorithm entry to the Quantum Algorithms sheet.
    """
    try:
        sheet = get_quantum_algorithms_sheet()
        
        # Get headers to understand column structure
        headers = sheet.row_values(1)
        
        # Create a row with empty values
        row = [''] * len(headers)
        
        # Map our data to the correct columns
        column_mapping = {
            'Unnamed: 0': str(problem_number),
            'Family Name': family_name,
            'Looked at?': '1.0',  # Mark as looked at
            'Variation': variation,
            'Algorithm Description': algorithm_description or 'Quantum algorithm',
            'Exact Problem Statement?': '1',
            'Exact algorithm?': '1.0',
            'Algorithm Name': algorithm_name,
            'Year': str(year),
            'Paper/Reference Link': paper_link,
            'DOI': doi or '',
            'Authors': authors,
            'Number of Authors': str(len(authors.split(',')) if authors else 1),
            'Title': title,
            'Time Complexity / Circuit Depth (Worst Only)': time_complexity or '',
            'Parameter definitions': parameter_definitions or '',
            'Computational Model': computational_model,
            'Space (QBit) Complexity (Auxiliary)': space_complexity or '',
            'Quantum?': '1.0',  # This is a quantum algorithm
        }
        
        # Fill in the row based on headers
        for i, header in enumerate(headers):
            if header in column_mapping:
                row[i] = column_mapping[header]
        
        # Append the row
        sheet.append_row(row, value_input_option='USER_ENTERED')
        
        return {
            "success": True,
            "message": f"Added quantum algorithm: {algorithm_name} ({year})",
            "title": title,
            "paper_link": paper_link
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    if tool_name == "get_subproblems":
        result = get_subproblems(tool_input["problem_number"])
    elif tool_name == "search_quantum_papers":
        result = search_quantum_papers(
            tool_input["problem_name"],
            tool_input.get("max_results", 10)
        )
    elif tool_name == "get_existing_quantum_algorithms":
        result = get_existing_quantum_algorithms(tool_input.get("problem_number"))
    elif tool_name == "add_quantum_algorithm":
        result = add_quantum_algorithm(**tool_input)
    elif tool_name == "finish":
        result = {
            "success": True,
            "status": "completed",
            **tool_input
        }
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    
    return json.dumps(result, indent=2, default=str)

# =============================================================================
# ReAct Agent System Prompt
# =============================================================================
SYSTEM_PROMPT = """You are a research assistant specialized in finding and cataloging quantum algorithms for the AlgoWiki project.

Your task is to:
1. Take a problem number from the user (e.g., 1 for Sorting)
2. Look up all subproblems/variations under that problem number using the get_subproblems tool
3. For each subproblem, search arXiv for quantum algorithm papers using search_quantum_papers
4. Check for duplicates using get_existing_quantum_algorithms before adding new entries
5. Add genuinely new quantum algorithms to the Google Sheet using add_quantum_algorithm
6. Call finish when done with a summary

IMPORTANT GUIDELINES:

**ReAct Format**: Always think step-by-step. Start each response with "Thought:" explaining your reasoning, then take an action.

**Duplicate Prevention**: 
- ALWAYS check existing entries first before adding
- Compare arXiv IDs and titles to avoid duplicates
- Skip papers that are already in the sheet

**Quality Filtering**:
- Only add papers that describe quantum algorithms (not just classical algorithms or quantum computing theory)
- The paper should propose or analyze an algorithm that solves the specific problem
- Look for complexity analysis, circuit depth, or qubit requirements in abstracts

**Data Extraction**:
- Extract time complexity from the abstract if mentioned (look for O() notation)
- Note the computational model (quantum circuit, adiabatic, etc.)
- Include all authors
- Use the arXiv PDF URL as the paper link

**Systematic Approach**:
- Process ONE subproblem at a time
- Search, review results, add relevant new papers, then move to next subproblem
- Keep track of what you've added to report in the final summary

Remember: Quality over quantity. Only add papers that are clearly about quantum algorithms for the specific problem."""

# =============================================================================
# Agent Loop
# =============================================================================
def run_agent(problem_number: int, verbose: bool = True, api_key: str = None):
    """
    Run the ReAct agent for a given problem number.
    """
    if not api_key:
        api_key = get_api_key()
        if not api_key:
            print("No API key provided. Exiting.")
            return {"error": "No API key"}
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # Initial user message
    user_message = f"""Please research quantum algorithms for problem number {problem_number}.

Steps to follow:
1. First, use get_subproblems to find all variations under problem {problem_number}
2. Check existing entries with get_existing_quantum_algorithms for problem {problem_number}
3. For each subproblem/variation, search for quantum algorithm papers
4. Add any new, relevant quantum algorithms you find (avoiding duplicates)
5. Finish with a summary of what was found and added

Begin!"""

    messages = [{"role": "user", "content": user_message}]
    
    if verbose:
        print("=" * 70)
        print(f"STARTING AGENT: Researching quantum algorithms for problem #{problem_number}")
        print("=" * 70)
        print(f"\nUser: {user_message}\n")
    
    steps = []
    finished = False
    
    for step_num in range(1, MAX_AGENT_STEPS + 1):
        if verbose:
            print(f"\n{'='*70}")
            print(f"STEP {step_num}")
            print("=" * 70)
        
        # Call Claude
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )
        
        # Process response
        assistant_content = response.content
        
        # Extract thought (text before tool use)
        thought_text = ""
        tool_uses = []
        
        for block in assistant_content:
            if block.type == "text":
                thought_text = block.text
                if verbose and thought_text:
                    # Extract and display Thought
                    if "Thought:" in thought_text:
                        print(f"\n{thought_text}")
                    else:
                        print(f"\nThought: {thought_text}")
            elif block.type == "tool_use":
                tool_uses.append(block)
        
        # Add assistant message to history
        messages.append({"role": "assistant", "content": assistant_content})
        
        # Process tool calls
        if tool_uses:
            tool_results = []
            
            for tool_use in tool_uses:
                tool_name = tool_use.name
                tool_input = tool_use.input
                
                if verbose:
                    print(f"\nAction: {tool_name}")
                    print(f"Input: {json.dumps(tool_input, indent=2)}")
                
                # Execute the tool
                result = execute_tool(tool_name, tool_input)
                
                if verbose:
                    # Truncate long results for display
                    result_display = result[:1500] + "..." if len(result) > 1500 else result
                    print(f"\nObservation: {result_display}")
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result
                })
                
                # Check if finish was called
                if tool_name == "finish":
                    finished = True
                    result_data = json.loads(result)
                    steps.append({
                        "step": step_num,
                        "thought": thought_text,
                        "action": tool_name,
                        "result": result_data
                    })
            
            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})
        
        # Track step
        steps.append({
            "step": step_num,
            "thought": thought_text,
            "actions": [tu.name for tu in tool_uses]
        })
        
        # Check if done
        if finished:
            if verbose:
                print("\n" + "=" * 70)
                print("AGENT COMPLETED")
                print("=" * 70)
            break
        
        # Check stop reason
        if response.stop_reason == "end_turn" and not tool_uses:
            if verbose:
                print("\nAgent ended without calling finish. Final response:")
                print(thought_text)
            break
    
    return {
        "problem_number": problem_number,
        "steps": steps,
        "total_steps": len(steps),
        "completed": finished
    }

# =============================================================================
# Main Entry Point
# =============================================================================
def main():
    """Main function to run the agent."""
    print("\n" + "=" * 70)
    print("AlgoWiki Quantum Algorithm Research Agent")
    print("=" * 70)
    
    # Get API key first
    api_key = get_api_key()
    if not api_key:
        print("Cannot run without API key. Exiting.")
        return
    
    print(f"\n✓ API key configured (starts with {api_key[:10]}...)")
    
    # Show available problem numbers from the Problems sheet
    print("\nLoading problem list...")
    try:
        df = pd.read_excel(LOCAL_EXCEL_PATH, sheet_name="Problems")
        problems = df.groupby('Old Family #')['Family Name'].first().dropna()
        
        print("\nAvailable Problems:")
        print("-" * 50)
        for num, name in sorted(problems.items())[:20]:  # Show first 20
            print(f"  {int(num):3d}. {name}")
        print("  ... (and more)")
        print("-" * 50)
    except FileNotFoundError:
        print(f"\n⚠ Excel file not found at: {LOCAL_EXCEL_PATH}")
        print("Please update LOCAL_EXCEL_PATH in the script to point to your Excel file.")
        return
    except Exception as e:
        print(f"Note: Could not load problem list: {e}")
    
    # Get user input
    try:
        problem_input = input("\nEnter problem number to research (e.g., 1 for Sorting): ").strip()
        problem_number = int(problem_input)
    except ValueError:
        print("Invalid input. Please enter a number.")
        return
    except KeyboardInterrupt:
        print("\nCancelled.")
        return
    
    # Run the agent
    print(f"\nStarting research for problem #{problem_number}...")
    result = run_agent(problem_number, verbose=True, api_key=api_key)
    
    # Print final summary
    if result and "error" not in result:
        print("\n" + "=" * 70)
        print("FINAL REPORT")
        print("=" * 70)
        print(f"Problem researched: #{result['problem_number']}")
        print(f"Total steps taken: {result['total_steps']}")
        print(f"Completed successfully: {result['completed']}")


if __name__ == "__main__":
    main()