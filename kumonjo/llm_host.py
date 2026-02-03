"""
LLM Host: Custom MCP client that uses Claude (via Vertex AI) as the orchestrator.

This module connects to the kumonjo MCP server and uses Claude to decide
which tools to call based on user questions.

Architecture:
    User → LLMHost → Claude (Vertex AI) → MCP Client → MCP Server → Tools

Requires:
    - GCP project with Vertex AI API enabled
    - GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION env vars (or gcloud configured)
    - anthropic[vertex] package
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env for any additional config
load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass
class Message:
    """Chat message."""
    role: str  # "user" or "assistant"
    content: str


@dataclass
class ChatSession:
    """Maintains conversation state."""
    messages: list[Message] = field(default_factory=list)

    def add_user_message(self, content: str):
        self.messages.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str):
        self.messages.append(Message(role="assistant", content=content))

    def to_api_messages(self) -> list[dict]:
        """Convert to API message format."""
        return [{"role": m.role, "content": m.content} for m in self.messages]


def _convert_mcp_tool_to_claude(mcp_tool: dict) -> dict:
    """Convert MCP tool schema to Claude tool format."""
    return {
        "name": mcp_tool["name"],
        "description": mcp_tool.get("description", ""),
        "input_schema": mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
    }


def _get_claude_client():
    """
    Get Claude client - tries Vertex AI first, falls back to direct Anthropic API.

    For Vertex AI, requires:
        - GOOGLE_CLOUD_PROJECT (or CLOUD_ML_PROJECT_ID)
        - GOOGLE_CLOUD_LOCATION (default: us-east5)

    For direct API, requires:
        - ANTHROPIC_API_KEY
    """
    from anthropic import Anthropic

    # Check for Vertex AI configuration
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("CLOUD_ML_PROJECT_ID")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-east5")

    if project_id:
        try:
            from anthropic import AnthropicVertex
            logger.info("Using Claude via Vertex AI (project=%s, location=%s)", project_id, location)
            return AnthropicVertex(project_id=project_id, region=location)
        except ImportError:
            logger.warning("anthropic[vertex] not installed, falling back to direct API")
        except Exception as e:
            logger.warning("Vertex AI init failed: %s, falling back to direct API", e)

    # Fall back to direct Anthropic API
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        logger.info("Using Claude via direct Anthropic API")
        return Anthropic(api_key=api_key)

    raise ValueError(
        "No Claude API configuration found. Set either:\n"
        "  - GOOGLE_CLOUD_PROJECT for Vertex AI, or\n"
        "  - ANTHROPIC_API_KEY for direct API"
    )


class LLMHost:
    """
    MCP Host that uses Claude as the orchestrator.

    Connects to the MCP server, gets available tools, and uses Claude
    to decide which tools to call based on user input.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_turns: int = 10,
        system_prompt: str | None = None,
    ):
        self.model = model
        self.max_turns = max_turns
        self.system_prompt = system_prompt or self._default_system_prompt()
        self._client = None
        self._mcp_tools: list[dict] = []
        self._claude_tools: list[dict] = []

    def _default_system_prompt(self) -> str:
        return """あなたは日本の政府統計データ（e-Stat）を検索・取得・分析するアシスタントです。

利用可能なツール:
1. discover_datasets - キーワードや年でデータセットを検索
2. retrieve_and_process - statsDataIdでテーブルデータを取得
3. analyze - 取得したデータの分析（集計、フィルタ、時系列など）
4. catalog_overview - 利用可能な年と統計分野の概要
5. list_available_tools - 利用可能なツール一覧

基本フロー:
1. ユーザーの質問からデータセットを検索 (discover_datasets)
2. 必要なデータを取得 (retrieve_and_process)
3. 必要に応じて分析 (analyze)

日本語で回答してください。"""

    @property
    def client(self):
        if self._client is None:
            self._client = _get_claude_client()
        return self._client

    async def connect_to_mcp_server(self):
        """Connect to the MCP server and get available tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Path to our MCP server
        server_script = Path(__file__).parent.parent / "mcp_server" / "server.py"

        logger.info("Connecting to MCP server: %s", server_script)

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_script)],
            env={**os.environ},
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the connection
                await session.initialize()

                # Get available tools
                tools_response = await session.list_tools()
                self._mcp_tools = [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in tools_response.tools
                ]
                self._claude_tools = [_convert_mcp_tool_to_claude(t) for t in self._mcp_tools]

                logger.info("Connected to MCP server, %d tools available", len(self._mcp_tools))
                return session

    async def call_mcp_tool(self, session, tool_name: str, tool_input: dict) -> str:
        """Call an MCP tool and return the result as a string."""
        logger.info("Calling MCP tool: %s(%s)", tool_name, json.dumps(tool_input, ensure_ascii=False)[:200])

        try:
            result = await session.call_tool(tool_name, tool_input)
            # MCP returns content blocks, extract text
            if result.content:
                texts = [c.text for c in result.content if hasattr(c, 'text')]
                return "\n".join(texts) if texts else str(result.content)
            return "Tool returned no content"
        except Exception as e:
            logger.error("MCP tool call failed: %s", e)
            return f"Error calling tool: {e}"

    async def chat(self, user_input: str, session: ChatSession | None = None) -> str:
        """
        Process a user message and return the assistant's response.

        This handles the full tool-use loop:
        1. Send user message to Claude with available tools
        2. If Claude wants to use a tool, call it via MCP
        3. Send tool result back to Claude
        4. Repeat until Claude gives a final response
        """
        if session is None:
            session = ChatSession()

        session.add_user_message(user_input)

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_script = Path(__file__).parent.parent / "mcp_server" / "server.py"
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_script)],
            env={**os.environ},
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()

                # Get tools if not already loaded
                if not self._claude_tools:
                    tools_response = await mcp_session.list_tools()
                    self._mcp_tools = [
                        {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                        for t in tools_response.tools
                    ]
                    self._claude_tools = [_convert_mcp_tool_to_claude(t) for t in self._mcp_tools]

                # Tool use loop
                messages = session.to_api_messages()

                for turn in range(self.max_turns):
                    logger.debug("Turn %d, sending %d messages to Claude", turn + 1, len(messages))

                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=4096,
                        system=self.system_prompt,
                        tools=self._claude_tools,
                        messages=messages,
                    )

                    # Check if we have a final text response
                    assistant_text = ""
                    tool_uses = []

                    for block in response.content:
                        if block.type == "text":
                            assistant_text += block.text
                        elif block.type == "tool_use":
                            tool_uses.append(block)

                    if response.stop_reason == "end_turn" or not tool_uses:
                        # Final response
                        session.add_assistant_message(assistant_text)
                        return assistant_text

                    # Handle tool calls
                    messages.append({
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": assistant_text} if assistant_text else None,
                            *[{
                                "type": "tool_use",
                                "id": t.id,
                                "name": t.name,
                                "input": t.input,
                            } for t in tool_uses]
                        ]
                    })
                    # Filter out None
                    messages[-1]["content"] = [c for c in messages[-1]["content"] if c]

                    # Call tools and collect results
                    tool_results = []
                    for tool_use in tool_uses:
                        result = await self.call_mcp_tool(
                            mcp_session,
                            tool_use.name,
                            tool_use.input,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                    messages.append({"role": "user", "content": tool_results})

                # Max turns reached
                return "申し訳ありません。処理が完了しませんでした。"

    async def chat_loop(self):
        """Run an interactive chat loop."""
        print("=" * 60)
        print("Kumonjo Chat - 日本政府統計データアシスタント")
        print("Claude via", "Vertex AI" if os.environ.get("GOOGLE_CLOUD_PROJECT") else "Anthropic API")
        print("Type 'quit' or 'exit' to end the session")
        print("=" * 60)

        session = ChatSession()

        while True:
            try:
                user_input = input("\n👤 You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "q"):
                    print("さようなら！")
                    break

                print("\n🤖 Assistant: ", end="", flush=True)
                response = await self.chat(user_input, session)
                print(response)

            except KeyboardInterrupt:
                print("\n\nさようなら！")
                break
            except Exception as e:
                logger.exception("Error in chat loop")
                print(f"\nError: {e}")


async def run_chat():
    """Entry point for running the chat."""
    host = LLMHost()
    await host.chat_loop()


def main():
    """Sync entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)

    asyncio.run(run_chat())


if __name__ == "__main__":
    main()
