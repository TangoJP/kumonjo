#!/usr/bin/env python3
"""
Interactive chat with kumonjo using Claude as the orchestrator.

Usage:
    python -m scripts.run_chat

    # With Vertex AI (GCP)
    export GOOGLE_CLOUD_PROJECT=your-project-id
    export GOOGLE_CLOUD_LOCATION=us-east5  # optional, defaults to us-east5
    python -m scripts.run_chat

    # With direct Anthropic API
    export ANTHROPIC_API_KEY=your-api-key
    python -m scripts.run_chat

    # Single query mode (non-interactive)
    python -m scripts.run_chat --query "2024年の人口統計を教えて"

Options:
    --query, -q     Single query mode (non-interactive)
    --model, -m     Model to use (default: claude-sonnet-4-20250514)
    --verbose, -v   Enable debug logging
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from kumonjo.llm_host import LLMHost, ChatSession


async def single_query(query: str, model: str) -> str:
    """Run a single query and return the response."""
    host = LLMHost(model=model)
    return await host.chat(query)


async def interactive_chat(model: str):
    """Run interactive chat loop."""
    host = LLMHost(model=model)
    await host.chat_loop()


def main():
    parser = argparse.ArgumentParser(
        description="Chat with kumonjo using Claude as the orchestrator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--query", "-q",
        help="Single query mode (non-interactive)",
    )
    parser.add_argument(
        "--model", "-m",
        default="claude-sonnet-4-20250514",
        help="Model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    # Reduce noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    if args.query:
        # Single query mode
        response = asyncio.run(single_query(args.query, args.model))
        print(response)
    else:
        # Interactive mode
        asyncio.run(interactive_chat(args.model))


if __name__ == "__main__":
    main()
