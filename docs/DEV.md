# mindX Agent Architecture: A Developer's Guide
Version: BDIAgent v3.0 | SimpleCoder v6.0 <br />
Author: PYTHAI mindX Team <br />
Status: Production Ready
# Introduction: The Brain and The Hands
In any advanced AI system, a clear separation of concerns between reasoning and execution is paramount for creating robust, secure, and understandable agents. The mindX agent architecture embodies this principle through two core components:
The Brain: BDIAgent<br />
This is the cognitive core of the system. Built on a Belief-Desire-Intention (BDI) model, it perceives the world, forms beliefs, deliberates on its goals (desires), and, most importantly, generates abstract plans (intentions) to achieve those goals. It decides what to do and why.
The Hands: SimpleCoder<br />
This is the execution layer. Its sole purpose is to provide a secure, stateful, and sandboxed terminal session. It does not reason or plan. It receives concrete, explicit commands from the BDIAgent and executes them within a heavily restricted environment. It decides how to do it safely.
Core Philosophy: The BDIAgent thinks, plans, and commands. The SimpleCoder tool obeys, executes, and reports, all within the confines of its sandbox. This separation makes the system secure by design and easier to debug.
#  System Architecture: The Two Pillars
Pillar 1: The BDI Brain (BDIAgent)
The BDIAgent operates on a continuous Perceive-Deliberate-Plan-Execute cycle, driven by a formal state machine (AgentStatus Enum)
```txt
+-------------------------------------------------+
      |                                                 |
      |   (Updates Beliefs)                             |
      |    +-----------+      (Selects Goal)      +------------+
      +--->| PERCEIVE  +------------------------->| DELIBERATE |
           +-----------+                          +------------+
                 ^                                       |
                 |                                (Forms Intention)
                 |                                       |
           (Action Result)                               v
           +-----------+                          +------------+
           | EXECUTE   |<-------------------------+    PLAN    |
           +-----------+      (Generates Plan)      +------------+
                 |
                 v
           (Affects World)
```
Beliefs: A knowledge store (BeliefSystem) holding the agent's understanding of the world, tagged with confidence and source.
Desires: A priority queue of goals. The agent's primary objective is to satisfy these desires.
Intentions: A concrete, step-by-step plan to achieve the current highest-priority goal. The BDIAgent uses its internal LLM to generate this plan, which is then rigorously validated before it becomes an intention.<br /><br />
Pillar 2: The Sandboxed Hands (SimpleCoder)
SimpleCoder provides the environment in which the BDIAgent's plans are realized. Its security model is non-negotiable.
The Sandbox Jail
On initialization, SimpleCoder establishes a sandbox_root directory. No operation is ever allowed to read, write, or execute outside this directory
```txt
+--------------------------------------------------+
| Host Filesystem (/home/user/)                    |
|                                                  |
|  +---------------------------------------------+ |
|  | mindX Project Root                          | |
|  |                                             | |
|  |  +----------------------------------------+ | |
|  |  | SANDBOX ROOT (e.g., tools/agent_ws)    | | |
|  |  |                                        | | |
|  |  |  +----------------+  +---------------+ | | |
|  |  |  | my_first_proj/ |  | my_second_proj/ | | | |
|  |  |  |  +-.venv/      |  |               | | | |
|  |  |  |  +-app.py      |  +---------------+ | | |
|  |  |  +----------------+                    | | |
|  |  +----------------------------------------+ | |
|  |      ^                                     | |
|  |      |  ALL AGENT ACTIVITY IS CONFINED HERE | |
|  |                                             | |
|  +---------------------------------------------+ |
|                                                  |
+--------------------------------------------------+
```
# A Stateful Session
SimpleCoder is not a collection of stateless functions. It maintains a session state:
Current Working Directory (CWD): The agent can cd into subdirectories.<br /><br />
Active Virtual Environment: The agent can create_venv and activate_venv. Once active, all run commands for python and pip are automatically routed to the venv's isolated executables.
Autonomous Mode: A safety switch that must be enabled for destructive commands like rm.
# The Integration Layer: How Brain Controls Hands
The connection between the BDIAgent and SimpleCoder is explicit and structured. The agent does not "chat" with its tool; it issues formal commands as part of a validated plan.
# The Plan: A Contract for Execution
When the BDIAgent needs to act, its internal LLM generates a plan. This plan is a JSON list of actions. To use SimpleCoder, it generates an EXECUTE_TOOL action.
Example Plan Snippet (JSON):
```json
[
  {
    "type": "THINK",
    "params": {
      "thought": "First, I need to create a directory for my new project."
    }
  },
  {
    "type": "EXECUTE_TOOL",
    "params": {
      "tool_id": "simple_coder",
      "command": "mkdir",
      "path": "my_web_app"
    }
  },
  {
    "type": "EXECUTE_TOOL",
    "params": {
      "tool_id": "simple_coder",
      "command": "cd",
      "path": "my_web_app"
    }
  }
]
```
# The Execution Flow
This diagram shows the call stack when the agent executes the mkdir action from the plan above
```txt
BDIAgent                                                   SimpleCoder
    |                                                            |
    | run() loop begins                                          |
    |                                                            |
    | _execute_intention()                                       |
    |   - Gets action: {type: "EXECUTE_TOOL", ...}               |
    |                                                            |
    | _action_execute_tool(params) -----------------------------> |
    |   - Finds 'simple_coder' in its tool registry              | execute(**params)
    |   - Calls tool.execute(**params)                           |   - Receives: {tool_id:'...', command:'mkdir', path:'...'}
    |                                                            |   - Finds 'mkdir' in its native_handlers
    |                                                            |   - Calls self._create_directory(path='my_web_app')
    |                                                            |     - _resolve_and_check_path('my_web_app') -> OK
    |                                                            |     - Path.mkdir()
    |                                                            |   - Returns: {'status':'SUCCESS', ...}
    |                                                            |
    | <----------------------------------------------------------+
    |   - Receives {'status':'SUCCESS', ...} from tool           |
    |   - Result is SUCCESS                                      |
    |                                                            |
    | _on_action_completed(success=True, ...)                    |
    |   - Moves to the next action in the plan                   |
    |                                                            |
```
# Developer Usage & Workflow Example
A developer's primary interaction is to give the BDIAgent a high-level goal. The agent's internal LLM then formulates the plan and uses SimpleCoder to execute it.
Goal: "Create a Python project named 'api_client', set up a virtual environment, install the 'httpx' library, and create a basic script to ping the GitHub API."
# Step 1: The Generated Plan
The BDIAgent's _plan method would produce a validated plan like this:
```json
[
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "mkdir", "path": "api_client"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "cd", "path": "api_client"}},
    {"type": "THINK", "params": {"thought": "Now I am inside the project directory. I will create a virtual environment."}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "create_venv", "venv_name": ".venv"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "activate_venv", "venv_name": ".venv"}},
    {"type": "THINK", "params": {"thought": "The venv is active. I will now install the httpx library using the venv's pip."}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "run", "command": "pip install httpx"}},
    {"type": "THINK", "params": {"thought": "Installation complete. I will now write the Python script."}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "write", "path": "main.py", "content": "import httpx\n\ndef check_github_api():\n    try:\n        r = httpx.get('https://api.github.com', timeout=10)\n        print(f'GitHub API Status: {r.status_code}')\n    except Exception as e:\n        print(f'An error occurred: {e}')\n\nif __name__ == '__main__':\n    check_github_api()"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "run", "command": "python main.py"}}
]
```
# Step 2: The Execution Log (Annotated)
A developer observing the logs would see the following interaction:
# --- BDIAgent Logs ---
bdi_agent - INFO - Deliberation: Selected goal 'Create a Python project...'
bdi_agent - INFO - Generating plan for goal: Create a Python project...
bdi_agent - INFO - Set new intention (Plan ID: plan_xxxx) with 10 actions...
bdi_agent - INFO - Executing action 'EXECUTE_TOOL' with params: {'tool_id': 'simple_coder', 'command': 'mkdir', 'path': 'api_client'}

# --- SimpleCoder Logs ---
tool.SimpleCoder - INFO - Directory created/ensured at api_client

# --- BDIAgent Logs ---
bdi_agent - INFO - Action 'EXECUTE_TOOL' SUCCEEDED. Result: {'status': 'SUCCESS', ...}
bdi_agent - INFO - Executing action 'EXECUTE_TOOL' with params: {'tool_id': 'simple_coder', 'command': 'cd', 'path': 'api_client'}

# --- SimpleCoder Logs ---
tool.SimpleCoder - INFO - Current directory is now: ./api_client

... this continues until the final step ...

# --- BDIAgent Logs ---
bdi_agent - INFO - Executing action 'EXECUTE_TOOL' with params: {'tool_id': 'simple_coder', 'command': 'run', 'command': 'python main.py'}

# --- SimpleCoder Logs ---
tool.SimpleCoder - INFO - Executing in '.../agent_workspace/api_client': ['python', 'main.py']

# --- BDIAgent Logs ---
bdi_agent - INFO - Action 'EXECUTE_TOOL' SUCCEEDED. Result: {'status': 'SUCCESS', 'stdout': 'GitHub API Status: 200', ...}
bdi_agent - INFO - Plan plan_xxxx completed.
bdi_agent - INFO - Goal 'primary_yyyy' achieved successfully.
bdi_agent - INFO - BDI run finished with final status: GOAL_ACHIEVED
Log
# PYTHAI mindX bdi_agent.py (brain) SimpleCoder (hands)
This two-component architecture provides a powerful and secure foundation for the mindX agent.
Key Strengths:
Security by Design: The hard separation between the reasoning layer (BDIAgent) and the sandboxed execution layer (SimpleCoder) is the primary security feature.<br /><br />
Modularity: SimpleCoder can be tested independently via its CLI. The BDIAgent can be given different sets of tools without changing its core logic.<br /><br />
Stateful Power: The agent can perform complex, multi-step tasks that require context (like activating a venv before installing packages) in a natural way.<br /><br />
Observability: The clear, structured plans and distinct log sources make debugging agent behavior significantly easier than in monolithic agent designs.<br /><br />
# Known Limitations:
The Semantic Gap: The system's success relies on the LLM's ability to generate a valid plan. If the LLM hallucinates a command or parameter, the system will fail gracefully (the action will fail validation), but the overall task will stall.<br /><br />
No Interactive Processes: The run command cannot manage shell commands that require real-time TTY input (e.g., ssh, vim).<br /><br />
Stateless Environment Variables: The session does not persist environment variables (export VAR=...) between run calls.<br /><br />
Sequential Execution: The agent executes one action at a time. It does not support running long-running background processes in parallel.<br /><br />
These limitations are deliberate design trade-offs to ensure security and simplicity, providing a solid foundation for future enhancements.<br /><br />
