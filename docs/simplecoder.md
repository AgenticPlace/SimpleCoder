# SimpleCoder Tool: Developer's Guide
Version: 7.0 (CLI & BDI Integration) <br />
Component: mindx/tools/simple_coder.py
# Philosophy
SimpleCoder is the primary execution tool for the mindX agent system. It is the component that directly interacts with the host filesystem and shell.
Its design is guided by a singular, critical philosophy: "Do one thing and do it well."
SimpleCoder's "one thing" is to provide a secure, stateful, and sandboxed terminal session. It is not a planner, a reasoner, or a knowledge base. It is a hardened execution engine that receives concrete commands and carries them out within a strictly defined boundary. Think of it as the agent's "hands"—strong and capable, but directed by the "brain" (BDIAgent).
This document provides a complete technical breakdown of its architecture, capabilities, and integration patterns.
# Architecture: The Sandboxed Session
The entire architecture of SimpleCoder is built to create and maintain a secure, isolated session for the agent. This session is defined by three key components.
#  The Filesystem Jail (sandbox_root)
Upon initialization, SimpleCoder establishes an absolute path to a sandbox_root directory. This directory is the agent's entire world. No operation is ever allowed to read, write, or execute outside this directory.
This is enforced by the private _resolve_and_check_path() method, which is the heart of the security model. It is called by every command that takes a path argument.
Workflow of _resolve_and_check_path(path_str):
Resolve: It takes a path string (e.g., my_project/main.py or ../.ssh/id_rsa) and resolves it to a full, absolute system path relative to the session's current working directory. This step is critical as it expands . and .., neutralizing traversal attempts.
Validate: It then checks if this absolute path is a child of the sandbox_root.
Result: If the path is inside the sandbox, it returns a valid pathlib.Path object. If it is outside, it logs a "Path Traversal DENIED" error and returns None, causing the calling command to fail safely.
# Session State Management
SimpleCoder is stateful. It maintains the context of the agent's session across multiple commands.
self.current_working_directory: A pathlib.Path object tracking the agent's location within the sandbox. It is initialized to sandbox_root and modified only by the cd command.
self.active_venv_bin_path: An optional pathlib.Path that points to the bin (or Scripts) directory of an activated virtual environment. When this is set, it's used to modify the PATH for run commands.
self.autonomous_mode: A boolean safety switch. It defaults to False. Destructive commands like rm are programmed to fail unless this is explicitly set to True, preventing accidental data loss from a faulty agent plan.
# The Native Command Toolkit (native_handlers)
SimpleCoder's functionality is exposed through a dispatch table of native, asynchronous Python methods. This approach is secure and scalable:
Security: By implementing core functions like ls, mkdir, and read in Python with pathlib, we bypass the host shell entirely for these operations, eliminating a whole class of injection vulnerabilities.
Scalability: Adding a new native command is as simple as writing a new async def _my_new_command() method and adding it to the native_handlers dictionary.
# Filesystem Commands
Command	Parameters	Description
ls	path: str = "."	Lists files and directories in the given path. Suffixes directories with /.
cd	path: str	Changes the session's current working directory.
read	path: str	Reads the full UTF-8 content of a specified file.
write	path: str, content: str	Writes string content to a file, creating parent directories if they don't exist.
mkdir	path: str	Creates a directory, including all necessary parents (like mkdir -p).
rm	path: str	Deletes a single file. Fails if autonomous_mode is False.
# Environment Management Commands
This is SimpleCoder's most powerful feature set, empowering the agent to manage its own development environments.
Command	Parameters	Description
create_venv	venv_name: str	Creates a Python virtual environment in the CWD (e.g., python -m venv <venv_name>).
activate_venv	venv_name: str	Simulates source. Sets the session's active_venv_bin_path to point to this venv.
deactivate_venv	(none)	Clears the active venv, reverting run commands to the system PATH.
# Execution Command
This is the secure gateway for running external programs.
Command	Parameters	Description
run	command: str	Executes an allowlisted shell command (e.g., git --version, pip install -r req.txt). It uses shlex.split() for safe argument parsing and automatically uses the active venv's PATH.
# Session Control Commands
Command	Parameters	Description
toggle_autonomous_mode	(none)	Toggles the safety switch for destructive operations.
help	(none)	Displays a list of available native commands.
SimpleCoder is designed to be used in two primary ways: by the BDIAgent as a tool, or directly via its CLI for testing.
# Usage by BDIAgent
The BDIAgent interacts with SimpleCoder via a single, unified entry point: the execute() method. The agent's plan will generate EXECUTE_TOOL actions that translate into calls to this method.
A BDIAgent Plan Step:
{
    "type": "EXECUTE_TOOL",
    "params": {
        "tool_id": "simple_coder",
        "command": "write",
        "path": "src/main.py",
        "content": "print('Hello from the agent!')"
    }
}
Use code with caution.
Json
The Corresponding Call within BDIAgent:
# The BDIAgent's _action_execute_tool handler finds the tool
simple_coder_tool = self.available_tools['simple_coder']

# It then calls the tool's execute method, unpacking the params
result = await simple_coder_tool.execute(**params)
# **params would be:
# {
#   'tool_id': 'simple_coder',
#   'command': 'write',
#   'path': 'src/main.py',
#   'content': "print('Hello from the agent!')"
# }
Use code with caution.
Python
The SimpleCoder.execute() Method:
This method acts as the master dispatcher.
# In simple_coder.py
async def execute(self, **kwargs) -> Dict[str, Any]:
    # 1. Get the command name
    command_name = kwargs.get("command") # -> "write"

    # 2. Look up the handler in the dispatch table
    handler = self.native_handlers.get(command_name) # -> self._write_file

    # 3. Prepare arguments for the specific handler
    handler_args = kwargs.copy()
    handler_args.pop("command", None) # -> {'path': 'src/main.py', 'content': ...}

    # 4. Call the specific handler with its arguments
    return await handler(**handler_args)
Use code with caution.
Python
This design ensures that all agent interactions flow through a single, secure, and well-defined entry point.
4.2. Usage via Command-Line Interface (CLI)
SimpleCoder can be run as a standalone, interactive script for testing and debugging. This is an invaluable feature for developers.
To Launch the CLI:
From the project root directory, run:
python -m tools.simple_coder
Use code with caution.
Bash
Interactive Session Example:
This simulates a developer setting up a project environment manually before handing off to an agent.
--- SimpleCoder Interactive Session ---
Type 'help' for a list of commands, or 'exit' to quit.
./ $ mkdir my_app
{
  "status": "SUCCESS",
  "message": "Directory created/ensured at my_app"
}
./ $ cd my_app
{
  "status": "SUCCESS",
  "message": "Current directory is now: ./my_app"
}
./my_app $ create_venv .venv
{
  "status": "SUCCESS",
  "message": "Venv '.venv' created. Activate it with: activate_venv '.venv'"
}
./my_app $ activate_venv .venv
{
  "status": "SUCCESS",
  "message": "Venv '.venv' is now active for this session."
}
(.venv) ./my_app $ run "pip install flask"
{
  "status": "SUCCESS",
  "return_code": 0,
  "stdout": "Collecting flask\n...",
  "stderr": ""
}
(.venv) ./my_app $ exit
Exiting.
Use code with caution.
This CLI mode allows developers to quickly test the behavior of the sandbox, verify that allowlisted commands work, and prepare complex environments for agent tasks.
