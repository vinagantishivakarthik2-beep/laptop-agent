"""
agent.py
--------
A natural-language chat agent for your laptop. Ask it things like:
  - "how much space is left on D drive?"
  - "what processor do I have?"
  - "when did my laptop last update?"
  - "how can I clean up my laptop?"

It uses Claude (via the Anthropic API) to understand your question and
decide which system-inspection tool(s) to call from system_tools.py.
Claude never runs commands directly — it only picks tools, and this
script executes them and reports the real results back.

Setup:
  1. pip install -r requirements.txt
  2. Set your API key:  setx ANTHROPIC_API_KEY "your-key-here"   (Windows, then reopen terminal)
     or just paste it when prompted on first run.
  3. Run:  python agent.py

Type 'exit' or 'quit' to stop.
"""

import os
import sys
import json

import anthropic
from system_tools import TOOL_DEFINITIONS, call_tool

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a helpful assistant running locally on the user's Windows laptop.
You answer questions about their machine — disk space, CPU, RAM, GPU, OS/update
history, battery, startup programs, and disk cleanup — by calling the provided tools
to get real, current data. Never guess or make up numbers; always call a tool first.

When answering:
- Be concise and direct. Lead with the actual answer (e.g. "You have 42.3 GB free on D:").
- For cleanup questions, call get_cleanup_report and summarize the biggest opportunities
  first, then list a few concrete next steps.
- If a tool returns an error (e.g. something requires admin rights), tell the user plainly
  and suggest running the script as Administrator if relevant.
- You can call multiple tools in one turn if the question needs more than one
  (e.g. "give me my full laptop specs" needs CPU + memory + system overview + GPU).
"""


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    print("No ANTHROPIC_API_KEY environment variable found.")
    key = input("Paste your Anthropic API key to continue: ").strip()
    if not key:
        print("An API key is required. Get one at https://console.anthropic.com/")
        sys.exit(1)
    return key


def run_tool_calls(content_blocks):
    """Execute every tool_use block Claude asked for, return tool_result blocks."""
    results = []
    for block in content_blocks:
        if block.type != "tool_use":
            continue
        print(f"  \u2192 checking {block.name}...")
        output = call_tool(block.name, block.input or {})
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(output, default=str),
        })
    return results


def chat_loop():
    client = anthropic.Anthropic(api_key=get_api_key())
    messages = []

    print("=" * 60)
    print(" Laptop Agent — ask me anything about this machine")
    print(" (disk space, specs, CPU, updates, cleanup, battery...)")
    print(" Type 'exit' to quit.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})

        # Loop in case Claude wants to call tools, see results, then call more tools.
        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_results = run_tool_calls(response.content)
                messages.append({"role": "user", "content": tool_results})
                continue  # let Claude see results and respond (or call more tools)

            # Final answer — print any text blocks.
            for block in response.content:
                if block.type == "text":
                    print(f"\nAgent: {block.text}")
            break


if __name__ == "__main__":
    chat_loop()
