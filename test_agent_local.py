#!/usr/bin/env python3
"""
Local Test Script for AlgoWiki Quantum Agent

This script tests the agent functionality without requiring Google Sheets.
It reads from the local Excel file and prints what would be added.
"""

import os
import json
import re
from datetime import datetime
from typing import Optional
import pandas as pd

# Try to import arxiv, provide helpful message if not available
try:
    import arxiv
    ARXIV_AVAILABLE = True
except ImportError:
    ARXIV_AVAILABLE = False
    print("Note: arxiv package not installed. Install with: pip install arxiv")

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Note: anthropic package not installed. Install with: pip install anthropic")

# Path to the local Excel file
LOCAL_EXCEL_PATH = "/mnt/user-data/uploads/AlgoWiki_algorithms__our_copy_.xlsx"

# =============================================================================
# Local Functions (no Google Sheets required)
# =============================================================================

def get_subproblems(problem_number: int) -> dict:
    """Get all subproblems for a given problem number."""
    try:
        df = pd.read_excel(LOCAL_EXCEL_PATH, sheet_name="Problems")
        filtered = df[df['Old Family #'] == float(problem_number)]
        
        if filtered.empty:
            return {"success": False, "error": f"No problems found with number {problem_number}"}
        
        family_name = filtered['Family Name'].iloc[0]
        variations = filtered['Variation'].dropna().tolist()
        aliases = filtered['Alias'].dropna().tolist()
        
        descriptions = []
        for _, row in filtered.iterrows():
            desc = {
                "variation": row['Variation'] if pd.notna(row['Variation']) else "General",
                "alias": row['Alias'] if pd.notna(row['Alias']) else None,
                "description": str(row['Problem Description'])[:300] if pd.notna(row['Problem Description']) else None
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


def get_existing_quantum_algorithms_local(problem_number: Optional[int] = None) -> dict:
    """Get existing quantum algorithms from the local Excel file."""
    try:
        df = pd.read_excel(LOCAL_EXCEL_PATH, sheet_name="Quantum Algorithms")
        
        entries = []
        for _, row in df.iterrows():
            entry = {
                "problem_number": row.iloc[0] if pd.notna(row.iloc[0]) else None,
                "family_name": row['Family Name'] if 'Family Name' in df.columns and pd.notna(row['Family Name']) else None,
                "variation": row['Variation'] if 'Variation' in df.columns and pd.notna(row['Variation']) else None,
                "title": row['Title'] if 'Title' in df.columns and pd.notna(row['Title']) else None,
                "paper_link": row['Paper/Reference Link'] if 'Paper/Reference Link' in df.columns and pd.notna(row['Paper/Reference Link']) else None,
            }
            
            if problem_number is not None:
                try:
                    entry_num = float(entry["problem_number"]) if entry["problem_number"] else None
                    if entry_num != float(problem_number):
                        continue
                except (ValueError, TypeError):
                    continue
            
            if entry["title"] or entry["paper_link"]:
                entries.append(entry)
        
        # Extract arXiv IDs
        existing_arxiv_ids = set()
        existing_titles = set()
        for entry in entries:
            if entry["paper_link"]:
                match = re.search(r'(\d{4}\.\d{4,5})', str(entry["paper_link"]))
                if match:
                    existing_arxiv_ids.add(match.group(1))
            if entry["title"]:
                existing_titles.add(str(entry["title"]).lower().strip())
        
        return {
            "success": True,
            "existing_entries": entries[:50],
            "existing_arxiv_ids": list(existing_arxiv_ids),
            "existing_titles": list(existing_titles)[:50],
            "total_entries": len(entries)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_quantum_papers(problem_name: str, max_results: int = 10) -> dict:
    """Search arXiv for quantum algorithm papers."""
    if not ARXIV_AVAILABLE:
        return {"success": False, "error": "arxiv package not installed"}
    
    try:
        query = f'(ti:quantum OR abs:quantum) AND (ti:"{problem_name}" OR abs:"{problem_name}") AND (cat:quant-ph OR cat:cs.DS OR cat:cs.CC)'
        
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        papers = []
        for result in client.results(search):
            arxiv_id = result.entry_id.split("/")[-1]
            arxiv_id_base = re.sub(r'v\d+$', '', arxiv_id)
            
            paper = {
                "arxiv_id": arxiv_id,
                "arxiv_id_base": arxiv_id_base,
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "year": result.published.year,
                "abstract": result.summary[:800],
                "pdf_url": result.pdf_url,
                "entry_url": result.entry_id,
                "doi": result.doi if result.doi else None,
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


def list_all_problems():
    """List all problems from the Problems sheet."""
    try:
        df = pd.read_excel(LOCAL_EXCEL_PATH, sheet_name="Problems")
        problems = df.groupby('Old Family #')['Family Name'].first().dropna()
        return dict(sorted(problems.items()))
    except Exception as e:
        print(f"Error loading problems: {e}")
        return {}


def list_quantum_algorithms_for_problem(problem_number: int):
    """List existing quantum algorithms for a problem."""
    result = get_existing_quantum_algorithms_local(problem_number)
    if result["success"]:
        return result["existing_entries"]
    return []


# =============================================================================
# Test Functions
# =============================================================================

def test_problem_lookup():
    """Test looking up problems and their subproblems."""
    print("\n" + "=" * 70)
    print("TEST: Problem Lookup")
    print("=" * 70)
    
    # List all problems
    problems = list_all_problems()
    print(f"\nFound {len(problems)} problem families:")
    for num, name in list(problems.items())[:15]:
        print(f"  {int(num):3d}. {name}")
    print("  ...")
    
    # Test specific problem
    test_problems = [1, 9, 6]  # Sorting, Linear System, Matrix Product
    for prob_num in test_problems:
        print(f"\n--- Problem #{prob_num} ---")
        result = get_subproblems(prob_num)
        if result["success"]:
            print(f"Family Name: {result['family_name']}")
            print(f"Variations: {result['variations'][:5]}...")
            print(f"Total subproblems: {result['total_subproblems']}")
        else:
            print(f"Error: {result['error']}")


def test_existing_quantum_algorithms():
    """Test reading existing quantum algorithms."""
    print("\n" + "=" * 70)
    print("TEST: Existing Quantum Algorithms")
    print("=" * 70)
    
    result = get_existing_quantum_algorithms_local()
    if result["success"]:
        print(f"\nTotal quantum algorithm entries: {result['total_entries']}")
        print(f"Unique arXiv IDs found: {len(result['existing_arxiv_ids'])}")
        
        print("\nSample entries:")
        for entry in result["existing_entries"][:5]:
            print(f"  - Problem {entry['problem_number']}: {entry['title'][:60]}..." if entry['title'] else f"  - Problem {entry['problem_number']}: (no title)")
    else:
        print(f"Error: {result['error']}")


def test_arxiv_search():
    """Test arXiv search functionality."""
    print("\n" + "=" * 70)
    print("TEST: arXiv Search")
    print("=" * 70)
    
    if not ARXIV_AVAILABLE:
        print("Skipping - arxiv package not installed")
        return
    
    test_queries = ["Linear System", "Sorting", "Maximum Flow"]
    
    for query in test_queries:
        print(f"\n--- Searching: '{query}' + quantum ---")
        result = search_quantum_papers(query, max_results=3)
        
        if result["success"]:
            print(f"Found {result['papers_found']} papers")
            for paper in result["papers"]:
                print(f"  - [{paper['year']}] {paper['title'][:70]}...")
        else:
            print(f"Error: {result['error']}")


def test_duplicate_detection():
    """Test duplicate detection logic."""
    print("\n" + "=" * 70)
    print("TEST: Duplicate Detection")
    print("=" * 70)
    
    # Get existing for problem 9 (Linear System)
    existing = get_existing_quantum_algorithms_local(9)
    
    if existing["success"]:
        print(f"\nExisting entries for problem #9: {existing['total_entries']}")
        print(f"Existing arXiv IDs: {existing['existing_arxiv_ids'][:5]}")
        
        # Search for papers
        if ARXIV_AVAILABLE:
            search_result = search_quantum_papers("Linear System", max_results=5)
            if search_result["success"]:
                print(f"\nNew search found {search_result['papers_found']} papers")
                
                new_papers = []
                duplicate_papers = []
                
                for paper in search_result["papers"]:
                    arxiv_id = paper["arxiv_id_base"]
                    title_lower = paper["title"].lower().strip()
                    
                    is_duplicate = (
                        arxiv_id in existing["existing_arxiv_ids"] or
                        title_lower in [t.lower() for t in existing["existing_titles"]]
                    )
                    
                    if is_duplicate:
                        duplicate_papers.append(paper)
                    else:
                        new_papers.append(paper)
                
                print(f"\nDuplicates found: {len(duplicate_papers)}")
                print(f"New papers to add: {len(new_papers)}")
                
                for paper in new_papers[:3]:
                    print(f"  NEW: [{paper['year']}] {paper['title'][:60]}...")
    else:
        print(f"Error: {existing['error']}")


def interactive_test():
    """Interactive test mode."""
    print("\n" + "=" * 70)
    print("INTERACTIVE TEST MODE")
    print("=" * 70)
    
    problems = list_all_problems()
    print("\nAvailable problems:")
    for num, name in list(problems.items())[:20]:
        print(f"  {int(num):3d}. {name}")
    
    try:
        prob_num = int(input("\nEnter problem number to test: "))
    except (ValueError, KeyboardInterrupt):
        print("Cancelled")
        return
    
    # Get subproblems
    print(f"\n--- Subproblems for #{prob_num} ---")
    subprobs = get_subproblems(prob_num)
    if subprobs["success"]:
        print(f"Family: {subprobs['family_name']}")
        for sp in subprobs["subproblems"][:5]:
            print(f"  - {sp['variation']}")
    
    # Get existing quantum algorithms
    print(f"\n--- Existing Quantum Algorithms for #{prob_num} ---")
    existing = get_existing_quantum_algorithms_local(prob_num)
    if existing["success"]:
        print(f"Found {existing['total_entries']} existing entries")
        for entry in existing["existing_entries"][:5]:
            print(f"  - {entry['title'][:60]}..." if entry['title'] else "  - (untitled)")
    
    # Search arXiv
    if ARXIV_AVAILABLE and subprobs["success"]:
        search_term = subprobs["family_name"]
        print(f"\n--- arXiv Search: '{search_term}' + quantum ---")
        search = search_quantum_papers(search_term, max_results=5)
        if search["success"]:
            print(f"Found {search['papers_found']} papers:")
            for paper in search["papers"]:
                is_dup = paper["arxiv_id_base"] in existing.get("existing_arxiv_ids", [])
                status = "[DUP]" if is_dup else "[NEW]"
                print(f"  {status} [{paper['year']}] {paper['title'][:55]}...")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("AlgoWiki Quantum Agent - Local Test Suite")
    print("=" * 70)
    
    print("\nSelect test to run:")
    print("  1. Problem Lookup")
    print("  2. Existing Quantum Algorithms")
    print("  3. arXiv Search")
    print("  4. Duplicate Detection")
    print("  5. Interactive Test")
    print("  6. Run All Tests")
    
    try:
        choice = input("\nEnter choice (1-6): ").strip()
    except KeyboardInterrupt:
        print("\nCancelled")
        return
    
    if choice == "1":
        test_problem_lookup()
    elif choice == "2":
        test_existing_quantum_algorithms()
    elif choice == "3":
        test_arxiv_search()
    elif choice == "4":
        test_duplicate_detection()
    elif choice == "5":
        interactive_test()
    elif choice == "6":
        test_problem_lookup()
        test_existing_quantum_algorithms()
        test_arxiv_search()
        test_duplicate_detection()
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
