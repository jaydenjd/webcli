#!/usr/bin/env python3
"""
Match Site - Match site pattern files based on user input

This module matches site pattern files based on user input and outputs
the matching site experience content.
"""

import re
import sys
from pathlib import Path


def match_site(query: str, patterns_dir: Path) -> None:
    """Match site pattern files based on query and output content."""
    if not query or not patterns_dir.exists():
        return
    
    for entry in patterns_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(".md"):
            continue
        
        domain = entry.name.replace(".md", "")
        raw = entry.read_text()
        
        # Extract aliases
        aliases = []
        for line in raw.split("\n"):
            if line.startswith("aliases:"):
                aliases_str = line.replace("aliases:", "").strip()
                aliases = [
                    v.strip()
                    for v in aliases_str.replace("[", "").replace("]", "").split(",")
                    if v.strip()
                ]
                break
        
        # Build match pattern
        def escape(text: str) -> str:
            return re.escape(text)
        
        pattern = "|".join(map(escape, [domain] + aliases))
        if not re.search(pattern, query, re.IGNORECASE):
            continue
        
        # Skip frontmatter, output body
        fences = list(re.finditer(r"^---\s*$", raw, re.MULTILINE))
        if len(fences) >= 2:
            body = raw[fences[1].end():].lstrip("\n")
        else:
            body = raw
        
        print(f"--- Site Experience: {domain} ---")
        print(body.rstrip() + "\n\n")


def main() -> None:
    """Main entry point."""
    # Get query from command line arguments
    query = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    
    # Get patterns directory
    script_dir = Path(__file__).parent.parent
    patterns_dir = script_dir / "references" / "site-patterns"
    
    match_site(query, patterns_dir)


if __name__ == "__main__":
    main()
