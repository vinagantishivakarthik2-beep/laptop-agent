# Laptop Agent

A natural-language chat agent that answers questions about your Windows laptop —
disk space, CPU/GPU, RAM, when it was last updated, battery, startup programs, and
how to clean it up — by actually querying your system, not guessing.

## use cases 
Scaling to Remote Servers
Laptop Agent is built around a simple pattern: the user asks a question in plain English, the model picks the right diagnostic tool, and real data comes back. The same pattern can be applied to remote servers in live projects.
Instead of logging into each server and manually checking disk space, CPU load, memory, pending updates, or startup services, an engineer could simply type a server name (for example, "Show me the status of web-server-02") and get a complete health summary in seconds.
Benefits
Saves time: no repeated logins and manual checks on every server.
One place for everything: disk, CPU, RAM, updates, and services in a single answer.
Faster troubleshooting: ask follow-ups like "Why is this server slow?" or "What changed since last update?"
Easier for non-experts: support staff don't need to remember commands.
Scales with the fleet: adding a server means adding its name to a list, not rewriting the tool.

How it would work: the existing tools would run over a remote connection (SSH for Linux, WinRM/PowerShell Remoting for Windows) against a named list of servers, using the same tool-calling flow.

## How it works

- `system_tools.py` — the "hands": real functions that call PowerShell/psutil to
  read disk usage, CPU/GPU/RAM info, Windows Update history, battery status, and
  scan temp folders for cleanup opportunities.
- `agent.py` — the "brain": a chat loop that sends your question to Claude along
  with a list of available tools. Claude decides which tool(s) answer your
  question, this script runs them, and Claude turns the real results into a
  plain-English answer.

Claude never executes anything on its own — it only *picks* which of the
functions above to call; your machine runs them locally.

## Setup

1. **Install Python 3.9+** if you don't have it (from python.org).

2. **Install dependencies** (open Command Prompt / PowerShell in this folder):
   ```
   pip install -r requirements.txt
   ```

3. **Get an Anthropic API key** at https://console.anthropic.com/ (Settings → API Keys).

4. **Set your API key** so you don't have to paste it every time:
   ```
   setx ANTHROPIC_API_KEY "your-key-here"
   ```
   Then close and reopen your terminal (setx only applies to new sessions).
   Alternatively, just run the agent and paste the key when prompted.

5. **Run it:**
   ```
   python agent.py
   ```

## Example questions to ask

- "How much space is left on D drive?"
- "What's the full configuration of my laptop?"
- "What processor do I have?"
- "How much RAM do I have and how much is free?"
- "When did my laptop last update?"
- "What graphics card is in this machine?"
- "How much battery do I have left?"
- "How can I clean up my laptop? What's taking up the most space?"
- "What programs launch at startup?"

## Notes on permissions

Some data (like full startup-program lists or clearing certain temp folders)
works best if you run your terminal **as Administrator**. If a tool reports an
error, the agent will tell you and suggest that.

## Extending it

To add a new capability:
1. Write a new function in `system_tools.py` that returns a dict.
2. Add it to `TOOL_FUNCTIONS` and describe it in `TOOL_DEFINITIONS`.
That's it — Claude will pick it up automatically next run based on its description.

## Cost note

Each question makes one or more small API calls to Claude (Sonnet). Usage is
very light for this kind of tool — typically a fraction of a cent per question —
but it does require a paid Anthropic API key (separate from a claude.ai subscription).
