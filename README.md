# mindX Agent Architecture
<a href="https://github.com/AgenticPlace/SimpleCoder/blob/main/docs/DEV.md">A Developer's Guide</a><br /><br />
Version: <a href="https://github.com/AgenticPlace/SimpleCoder/blob/main/bdi_agent_ID_aware.py">BDIAgent v3.0</a> | <a href="https://github.com/AgenticPlace/SimpleCoder/blob/main/simple_coder.py">SimpleCoder v7.0</a> <br />
Author: The mindX Team <br />
Status: Production Ready
# Introduction: The Brain and The Hands
In any advanced AI agent system, the separation of reasoning from execution is paramount for building robust, secure, and understandable agents. The mindX architecture embodies this principle through two core, synergistic components:<br />
# The Brain: BDIAgent
This is the cognitive core. Built on a Belief-Desire-Intention (BDI) model, it perceives the world, forms beliefs, deliberates on its goals (desires), and generates abstract, step-by-step plans (intentions) to achieve those goals. It determines what to do and why.<br />
# The Hands: SimpleCoder
This is the sandboxed execution layer. Its sole purpose is to provide a secure, stateful, and isolated terminal session. It does not reason; it receives concrete commands from the BDIAgent and executes them within a heavily restricted environment. It determines how to perform actions safely.<br /><br />
Core Philosophy: The BDIAgent thinks and commands. The SimpleCoder tool obeys and executes. This separation creates a system that is secure by design, where the unpredictable, creative nature of the LLM is channeled through a predictable, hardened execution engine.<br /><br />
# Explanation: The Sandboxed Session Model
SimpleCoder is not a stateless API; it's a self-contained, interactive session. To understand it, think of a developer using a sandboxed Docker container or a tmux session that is permanently "jailed" inside a specific project directory.<br /><br />
# Key Architectural Concepts
The Sandbox Jail<br /><br />
On initialization, SimpleCoder establishes a sandbox_root directory (e.g., mindx/tools/agent_workspace). No operation is ever allowed to escape this directory. This is the tool's most fundamental security guarantee, enforced by a robust path validation method that resolves and checks every file path provided by the agent.<br /><br />
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
SimpleCoder maintains an internal state to create a coherent session:<br />
Current Working Directory (CWD): The agent can cd into subdirectories.<br />
Active Virtual Environment: The agent can create_venv and activate_venv. Once active, all run commands for python and pip are automatically routed to the venv's isolated executables.
Autonomous Mode: A safety switch that must be enabled for destructive commands like rm.<br />
# Technical Implementation
The BDI Cycle (BDIAgent)<br /><br />
The BDIAgent operates on a continuous Deliberate-Plan-Execute loop, driven by a formal AgentStatus state machine.<br /><br />
Deliberate: It reviews its list of goals (desires) and selects the highest-priority pending goal.<br /><br />
Plan: It uses its internal LLM to generate a plan to achieve the selected goal. The LLM is given a strict list of available actions and tools to ground its output.<br /><br />
Validate: The generated plan (a JSON list of actions) is rigorously validated against a schema. If the plan is invalid (e.g., uses a non-existent tool or has a malformed structure), it is rejected, and the agent enters a FAILED_PLANNING state.<br /><br />
Execute: If the plan is valid, it becomes the agent's intention. The agent executes one action at a time, passing tool commands to the appropriate tool (like SimpleCoder).<br /><br />
# Venv Activation (SimpleCoder)
A shell's source command modifies the environment of the current process. Since SimpleCoder executes commands in child processes, it cannot be called directly. Instead, it is correctly and securely simulated:<br /><br />
The activate_venv command validates the target venv directory and stores its bin path in self.active_venv_bin_path.<br /><br />
When the run command is called, it creates a copy of the system environment (os.environ.copy())<br /><br />
If self.active_venv_bin_path is set, it prepends this path to the PATH variable within that copied environment.<br /><br />
The subprocess is then launched with this modified environment. The OS, when searching for python, finds the venv's version first, achieving perfect isolation.<br /><br />
# The Command Toolkit (SimpleCoder)
The agent's capabilities are exposed as a clean set of native, asynchronous Python methods, handled by a dispatch table.<br />
```txt
Command	Type	Description
ls	Native	Lists directory contents
cd	Native	Changes the stateful CWD
mkdir	Native	Creates directories (mkdir -p)
read	Native	Reads a file's content
write	Native	Writes content to a file
rm	Native	Deletes a file (requires autonomous mode)
create_venv	Native	Creates a Python virtual environment
activate_venv	Native	Activates a venv for the session
deactivate_venv	Native	Deactivates the session's venv
run	Native	Securely executes an allowlisted shell command
toggle_autonomous_mode	Native	Toggles the safety switch for rm
```
# Usage: A Standard Workflow
A developer's primary interaction is to give the BDIAgent a high-level goal. The agent then formulates the plan and uses SimpleCoder to execute it.<br /><br />
Goal: "Create a Python project named 'api_client', set up a virtual environment, install 'httpx', and create a script to ping the GitHub API."<br /><br />
Step 1: The Generated Plan<br /><br />
The BDIAgent's _plan method would produce a validated plan similar to this:
```json
[
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "mkdir", "path": "api_client"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "cd", "path": "api_client"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "create_venv", "venv_name": ".venv"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "activate_venv", "venv_name": ".venv"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "run", "command": "pip install httpx"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "write", "path": "main.py", "content": "import httpx; print(httpx.get('https://api.github.com').status_code)"}},
    {"type": "EXECUTE_TOOL", "params": {"tool_id": "simple_coder", "command": "run", "command": "python main.py"}}
]
```
Step 2: Execution Log<br /><br />
A developer observing the logs would see a clear, step-by-step execution, with log messages sourced from both the BDIAgent (reasoning) and SimpleCoder (action).<br />
```log
bdi_agent - INFO - Deliberation: Selected goal 'Create a Python project...'
bdi_agent - INFO - Set new intention (Plan ID: plan_xxxx) with 7 actions...
bdi_agent - INFO - Executing action 'EXECUTE_TOOL' with params: {'tool_id': 'simple_coder', 'command': 'mkdir', ...}
tool.SimpleCoder - INFO - Directory created/ensured at api_client
bdi_agent - INFO - Action 'EXECUTE_TOOL' SUCCEEDED.
...
tool.SimpleCoder - INFO - Executing in '.../agent_workspace/api_client': ['pip', 'install', 'httpx']
...
tool.SimpleCoder - INFO - Executing in '.../agent_workspace/api_client': ['python', 'main.py']
bdi_agent - INFO - Action 'EXECUTE_TOOL' SUCCEEDED. Result: {'status': 'SUCCESS', 'stdout': '200', ...}
bdi_agent - INFO - Plan plan_xxxx completed.
bdi_agent - INFO - BDI run finished with final status: GOAL_ACHIEVED
```
# Advanced Usage and Testing
While the agent is designed to be autonomous, SimpleCoder can also be run directly from the command line for testing, debugging, or manual environment setup.<br />
Interactive CLI Mode<br />
You can launch an interactive session to test the sandbox environment manually. From the project root, run:<br />
```python
python3 -m tools.simple_coder
```
This will drop you into a SimpleCoder shell where you can use the native commands directly:
```txt
--- SimpleCoder Interactive Session ---
Type 'help' for a list of commands, or 'exit' to quit.
./ $ ls
{
  "status": "SUCCESS",
  "items": []
}
./ $ mkdir test_project
{
  "status": "SUCCESS",
  "message": "Directory created/ensured at test_project"
}
./ $ cd test_project
{
  "status": "SUCCESS",
  "message": "Current directory is now: ./test_project"
}
./test_project $ create_venv .venv
{
  "status": "SUCCESS",
  "message": "Venv '.venv' created. Activate it with: activate_venv '.venv'"
}
./test_project $ activate_venv .venv
{
  "status": "SUCCESS",
  "message": "Venv '.venv' is now active for this session."
}
(.venv) ./test_project $ run "python --version"
{
  "status": "SUCCESS",
  "return_code": 0,
  "stdout": "Python 3.11.5",
  "stderr": ""
}
(.venv) ./test_project $ exit
Exiting.
```
This CLI is invaluable for:<br /><br />
Debugging: Quickly verifying that allowlisted shell commands work as expected.<br /><br />
Environment Scaffolding: Manually setting up a complex directory structure or installing base packages in a venv before handing a task to the agent.<br /><br />
Understanding Permissions: Testing what the agent can and cannot do within its jail.<br /><br />
# Summary and Limitations
This two-component architecture provides a powerful and secure foundation for the mindX agent system.<br /><br />
<a href="https://github.com/AgenticPlace/SimpleCoder/blob/main/simple_coder.py">Key Strengths</a>:<br /><br />
Security by Design: The hard separation between the reasoning layer and the sandboxed execution layer is the primary security feature.<br /><br />
Modularity: SimpleCoder can be tested independently via its CLI. The BDIAgent can be given different sets of tools without changing its core logic.<br /><br />
Stateful Power: The agent can perform complex, multi-step tasks that require context in a natural way.<br /><br />
Observability: The structured plans and distinct log sources make debugging agent behavior significantly easier than in monolithic agent designs.<br /><br />
Known Limitations:<br /><br />
The Semantic Gap: The system's success relies on the LLM's ability to generate a valid plan. If the LLM hallucinates a command or parameter, the system will fail gracefully (the action will fail validation), but the overall task will stall.<br /><br />
No Interactive Processes: The run command cannot manage shell commands that require real-time TTY input (e.g., ssh, vim).<br /><br />
Stateless Environment Variables: The session does not persist environment variables (export VAR=...) between run calls.<br /><br />
Sequential Execution: The agent executes one action at a time. It does not support running long-running background processes.<br /><br />
These <a href="https://github.com/AgenticPlace/SimpleCoder/blob/main/docs/technical.md">limitations</a> are deliberate design trade-offs to ensure security and simplicity, providing a solid foundation for future enhancements for mindX Augmentic Intelligence<br />
