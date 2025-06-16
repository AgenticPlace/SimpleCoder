# mindx/tools/simple_coder.py (Version 7 - CLI & BDI Integration)
"""
SimpleCoder: The Agent's Sandboxed Terminal Session

Core Philosophy: "Do one thing and do it well."
SimpleCoder's one thing is to provide a secure, stateful, and sandboxed
terminal session. It empowers the agent to create and manage its own isolated
Python virtual environments (`venv`) within the sandbox.

This version is fully compatible as a tool for BDIAgent v3.0+ and includes
a standalone interactive CLI for testing and direct use.

Key Features of this Architecture:
- Agent-Controlled Venvs: The agent can create and activate its own named
  venvs (e.g., 'simplesandbox').
- Simulated `source` Command: A native `activate_venv` command securely
  simulates `source bin/activate` for subprocesses.
- Guaranteed Sandbox Creation: The top-level sandbox directory is automatically
  created on initialization if it does not exist.
- Stateful CWD & BDI-Compatible `execute` Method.
- Standalone Interactive Command-Line Interface (CLI).
"""
import asyncio
import json
import shlex
import sys
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Awaitable, TypeAlias

# Assuming these stubs exist for context when running as part of the mindX project
try:
    from core.bdi_agent import BaseTool, AgentRegistryInterface
    from utils.config import Config, PROJECT_ROOT
    from utils.logging_config import get_logger
    from llm.llm_interface import LLMHandlerInterface
except ImportError:
    # Define dummy classes and variables for standalone execution
    print("Running in standalone mode. Defining dummy core classes.", file=sys.stderr)
    class BaseTool:
        def __init__(self, **kwargs): self.logger = logging.getLogger(self.__class__.__name__)
    class AgentRegistryInterface: pass
    class LLMHandlerInterface: pass
    class Config:
        def get(self, key, default=None): return default
    PROJECT_ROOT = Path(__file__).parent.parent.resolve()
    import logging
    def get_logger(name):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    try:
        from typing_extensions import TypeAlias
    except ImportError:
        TypeAlias = any

NativeHandler: TypeAlias = Callable[..., Awaitable[Dict[str, Any]]]

class SimpleCoder(BaseTool):
    """Provides a stateful, sandboxed terminal session for an AI agent."""

    def __init__(self, config: Optional[Config] = None, llm_handler: Optional[LLMHandlerInterface] = None, agent_registry: Optional[AgentRegistryInterface] = None, **kwargs):
        super().__init__(config=config, llm_handler=llm_handler, **kwargs)
        # LLM handler is optional for direct use, but BDI agent might require it.
        # self.agent_registry = agent_registry

        self.config_data: Dict[str, Any] = {}
        self.command_timeout: int = 60
        self._load_command_config()

        # Core state variables for the session
        self.sandbox_root: Path = self._initialize_sandbox()
        self.current_working_directory: Path = self.sandbox_root
        self.active_venv_bin_path: Optional[Path] = None
        self.autonomous_mode: bool = False

        # The agent's native command toolkit
        self.native_handlers: Dict[str, NativeHandler] = {
            "ls": self._list_directory,
            "cd": self._change_directory,
            "read": self._read_file,
            "write": self._write_file,
            "mkdir": self._create_directory,
            "rm": self._delete_file,
            "run": self._run_shell_command,
            "create_venv": self._create_venv,
            "activate_venv": self._activate_venv,
            "deactivate_venv": self._deactivate_venv,
            "toggle_autonomous_mode": self._toggle_autonomous_mode,
            "help": self._show_help,
        }
        self.logger.info(f"SimpleCoder session initialized. Sandbox jail at: {self.sandbox_root}")

    def _load_command_config(self):
        default_path = PROJECT_ROOT / "data" / "config" / "SimpleCoder.v6.config.json"
        config_path_str = os.getenv("SIMPLECODER_CONFIG", str(default_path))
        config_path = Path(config_path_str)
        
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    self.config_data = json.load(f)
                self.command_timeout = self.config_data.get("command_timeout_seconds", 60)
            except json.JSONDecodeError:
                self.logger.error(f"Invalid JSON in config file: {config_path}. Tool will not function.", exc_info=True)
        else:
            self.logger.warning(f"SimpleCoder config file not found at {config_path}. Using empty config.")

    def _initialize_sandbox(self) -> Path:
        """Creates the sandbox directory if it doesn't exist and returns its path."""
        default_sandbox = PROJECT_ROOT / "tools" / "agent_workspace"
        sandbox_path_str = self.config_data.get("sandbox_path", str(default_sandbox.relative_to(PROJECT_ROOT)))
        sandbox_abs_path = (PROJECT_ROOT / sandbox_path_str).resolve()
        
        # Use a more robust check that doesn't rely on Python 3.9+ specific features for the fallback
        try:
            sandbox_abs_path.relative_to(PROJECT_ROOT)
            if sandbox_abs_path == PROJECT_ROOT: raise ValueError()
        except ValueError:
             self.logger.critical(f"INSECURE SANDBOX CONFIG: '{sandbox_path_str}'. Defaulting to '{default_sandbox}'.")
             sandbox_abs_path = default_sandbox
            
        sandbox_abs_path.mkdir(parents=True, exist_ok=True)
        return sandbox_abs_path

    def _resolve_and_check_path(self, path_str: str) -> Optional[Path]:
        """Resolves a path relative to the CWD and ensures it's within the sandbox."""
        try:
            if Path(path_str).is_absolute():
                 self.logger.warning(f"Absolute path '{path_str}' provided. Treating it as relative to sandbox root.")
                 resolved_path = (self.sandbox_root / path_str.lstrip('/')).resolve()
            else:
                resolved_path = (self.current_working_directory / path_str).resolve()
            
            resolved_path.relative_to(self.sandbox_root)
            return resolved_path
        except ValueError:
            self.logger.error(f"Path Traversal DENIED. Attempt to access '{path_str}' which resolves outside the sandbox.")
            return None
        except Exception as e:
            self.logger.error(f"Path validation failed for '{path_str}': {e}", exc_info=True)
            return None

    # --- BDI Integration Point ---

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Main entry point for the BDIAgent.
        The BDIAgent's `_action_execute_tool` will call this method.
        It expects a 'command' key to dispatch to the correct native handler.
        """
        command_name = kwargs.get("command")
        if not command_name:
            return {"status": "ERROR", "message": "The 'command' parameter is missing."}

        handler = self.native_handlers.get(command_name)
        if not handler:
            return {"status": "ERROR", "message": f"Unknown command: '{command_name}'. Available commands are: {list(self.native_handlers.keys())}"}
        
        # Prepare arguments for the handler, removing the 'command' key.
        handler_args = kwargs.copy()
        handler_args.pop("command", None)

        try:
            return await handler(**handler_args)
        except TypeError as e:
            # This catches calls with wrong/missing parameters.
            return {"status": "ERROR", "message": f"Invalid parameters for command '{command_name}': {e}"}
        except Exception as e:
            self.logger.error(f"Unhandled exception in command '{command_name}': {e}", exc_info=True)
            return {"status": "ERROR", "message": "An internal error occurred during command execution."}

    # --- Native Session Commands ---

    async def _show_help(self) -> Dict[str, Any]:
        """Displays available commands and their purpose."""
        help_text = "SimpleCoder Native Commands:\n"
        for name, func in self.native_handlers.items():
            doc = func.__doc__.strip().split('\n')[0] if func.__doc__ else "No description."
            help_text += f"  - {name:<25} {doc}\n"
        return {"status": "SUCCESS", "content": help_text}

    async def _list_directory(self, path: str = ".") -> Dict[str, Any]:
        """Lists files and directories in a given path."""
        # ... (implementation from v6)
        dir_path = self._resolve_and_check_path(path)
        if not dir_path or not dir_path.is_dir(): return {"status": "ERROR", "message": f"Invalid directory: '{path}'"}
        items = sorted([f.name + ('/' if f.is_dir() else '') for f in dir_path.iterdir()])
        return {"status": "SUCCESS", "items": items}

    async def _change_directory(self, path: str) -> Dict[str, Any]:
        """Changes the current working directory of the session."""
        # ... (implementation from v6)
        new_dir = self._resolve_and_check_path(path)
        if not new_dir or not new_dir.is_dir(): return {"status": "ERROR", "message": f"Cannot cd into invalid directory: '{path}'"}
        self.current_working_directory = new_dir
        relative_cwd = self.current_working_directory.relative_to(self.sandbox_root)
        return {"status": "SUCCESS", "message": f"Current directory is now: ./{relative_cwd}"}

    async def _create_directory(self, path: str) -> Dict[str, Any]:
        """Creates a directory, including parents."""
        # ... (implementation from v6)
        dir_path = self._resolve_and_check_path(path)
        if not dir_path: return {"status": "ERROR", "message": "Invalid or insecure directory path provided."}
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"status": "SUCCESS", "message": f"Directory created/ensured at {path}"}

    async def _read_file(self, path: str) -> Dict[str, Any]:
        """Reads the content of a text file."""
        # ... (implementation from v6)
        file_path = self._resolve_and_check_path(path)
        if not file_path or not file_path.is_file(): return {"status": "ERROR", "message": f"File not found: {path}"}
        try:
            return {"status": "SUCCESS", "content": await asyncio.to_thread(file_path.read_text, encoding='utf-8')}
        except Exception as e: return {"status": "ERROR", "message": f"Error reading file: {e}"}

    async def _write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Writes content to a text file."""
        # ... (implementation from v6)
        file_path = self._resolve_and_check_path(path)
        if not file_path: return {"status": "ERROR", "message": "Invalid or insecure path provided."}
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(file_path.write_text, content, encoding='utf-8')
            return {"status": "SUCCESS", "message": "File written successfully."}
        except Exception as e: return {"status": "ERROR", "message": f"Error writing file: {e}"}

    async def _delete_file(self, path: str) -> Dict[str, Any]:
        """Deletes a file. Requires autonomous mode to be enabled."""
        # ... (implementation from v6)
        if not self.autonomous_mode:
            return {"status": "ERROR", "message": "Autonomous mode is not enabled. Cannot delete files. Use 'toggle_autonomous_mode'."}
        file_path = self._resolve_and_check_path(path)
        if not file_path or not file_path.is_file(): return {"status": "ERROR", "message": f"File not found or is a directory: {path}"}
        try:
            await asyncio.to_thread(file_path.unlink)
            return {"status": "SUCCESS", "message": "File deleted successfully."}
        except Exception as e: return {"status": "ERROR", "message": f"Error deleting file: {e}"}

    async def _toggle_autonomous_mode(self) -> Dict[str, Any]:
        """Toggles the safety switch for destructive operations like 'rm'."""
        self.autonomous_mode = not self.autonomous_mode
        return {"status": "SUCCESS", "message": f"Autonomous mode is now {'ENABLED' if self.autonomous_mode else 'DISABLED'}."}

    async def _create_venv(self, venv_name: str) -> Dict[str, Any]:
        """Creates a Python virtual environment."""
        # ... (implementation from v6)
        if not re.match(r'^[a-zA-Z0-9_.-]+$', venv_name): return {"status": "ERROR", "message": "Invalid venv_name."}
        venv_path = self._resolve_and_check_path(venv_name)
        if not venv_path: return {"status": "ERROR", "message": "Invalid or insecure venv path."}
        if venv_path.exists(): return {"status": "ERROR", "message": f"Directory or file '{venv_name}' already exists."}
        self.logger.info(f"Creating new venv in '{venv_path}'...")
        try:
            proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'venv', str(venv_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0: raise subprocess.CalledProcessError(proc.returncode, [sys.executable, '-m', 'venv'], stdout, stderr)
            return {"status": "SUCCESS", "message": f"Venv '{venv_name}' created. Activate it with: activate_venv '{venv_name}'"}
        except subprocess.CalledProcessError as e: return {"status": "ERROR", "message": f"Failed to create venv: {e.stderr.decode()}"}

    async def _activate_venv(self, venv_name: str) -> Dict[str, Any]:
        """Activates a venv for subsequent `run` commands."""
        # ... (implementation from v6)
        venv_path = self._resolve_and_check_path(venv_name)
        if not venv_path or not venv_path.is_dir(): return {"status": "ERROR", "message": f"Venv directory '{venv_name}' not found."}
        bin_path = venv_path / ('Scripts' if sys.platform == 'win32' else 'bin')
        if not (bin_path / 'python').exists() and not (bin_path / 'python.exe').exists(): return {"status": "ERROR", "message": f"'{venv_name}' does not appear to be a valid venv."}
        self.active_venv_bin_path = bin_path
        relative_venv_path = venv_path.relative_to(self.sandbox_root)
        return {"status": "SUCCESS", "message": f"Venv '{relative_venv_path}' is now active for this session."}

    async def _deactivate_venv(self) -> Dict[str, Any]:
        """Deactivates any active venv."""
        # ... (implementation from v6)
        if not self.active_venv_bin_path: return {"status": "SUCCESS", "message": "No venv was active."}
        self.active_venv_bin_path = None
        return {"status": "SUCCESS", "message": "Venv deactivated."}

    async def _run_shell_command(self, command: str) -> Dict[str, Any]:
        """Executes an allowlisted shell command, using the active venv if set."""
        # ... (implementation from v6)
        try:
            command_parts = shlex.split(command)
            command_name = command_parts[0]
        except (ValueError, IndexError): return {"status": "ERROR", "message": "Invalid command string."}
        if command_name not in self.config_data.get("allowed_shell_commands", []):
            return {"status": "ERROR", "message": f"Command '{command_name}' is not in the allowlist."}
        env = os.environ.copy()
        if self.active_venv_bin_path:
            env["PATH"] = f"{self.active_venv_bin_path}{os.pathsep}{env.get('PATH', '')}"
        self.logger.info(f"Executing in '{self.current_working_directory}': {command_parts}")
        try:
            process = await asyncio.wait_for(asyncio.create_subprocess_exec(*command_parts, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=self.current_working_directory, env=env), timeout=self.command_timeout)
            stdout, stderr = await process.communicate()
            result = {"status": "SUCCESS" if process.returncode == 0 else "FAILURE", "return_code": process.returncode, "stdout": stdout.decode('utf-8', 'ignore').strip(), "stderr": stderr.decode('utf-8', 'ignore').strip()}
            if result["status"] == "FAILURE": self.logger.warning(f"Shell command failed. Stderr: {result['stderr']}")
            return result
        except FileNotFoundError: return {"status": "ERROR", "message": f"Shell command not found: '{command_name}'."}
        except Exception as e: return {"status": "ERROR", "message": f"An exception occurred: {str(e)}"}

# --- Standalone CLI for Testing and Direct Interaction ---

async def main_cli():
    """The main entry point for the interactive command-line interface."""
    print("--- SimpleCoder Interactive Session ---")
    print("Type 'help' for a list of commands, or 'exit' to quit.")
    
    # Use dummy/stub objects for standalone operation
    coder = SimpleCoder(config=Config())

    while True:
        # Construct the prompt
        relative_cwd = f"./{coder.current_working_directory.relative_to(coder.sandbox_root)}"
        venv_indicator = f"({coder.active_venv_bin_path.parent.name}) " if coder.active_venv_bin_path else ""
        prompt = f"{venv_indicator}{relative_cwd} $ "
        
        try:
            line = input(prompt)
        except EOFError:
            print("\nExiting.")
            break
            
        if not line.strip():
            continue
        if line.strip().lower() == 'exit':
            print("Exiting.")
            break

        # Parse the command and arguments
        parts = shlex.split(line)
        command_name = parts[0]
        
        # This simple parser converts list-style args into a kwargs dict for execute()
        # e.g., `write "file.txt" "hello"` -> {'command': 'write', 'path': 'file.txt', 'content': 'hello'}
        args_dict = {"command": command_name}
        if command_name == 'write':
            if len(parts) > 2: args_dict.update({'path': parts[1], 'content': ' '.join(parts[2:])})
        elif command_name == 'run':
            if len(parts) > 1: args_dict['command_str'] = ' '.join(parts[1:]) # The 'run' handler expects a single string
        elif len(parts) > 1:
            # A generic way to handle other commands with one argument
            # This is a simplification for the CLI
            arg_name_map = {'cd': 'path', 'ls': 'path', 'mkdir': 'path', 'rm': 'path', 'read': 'path', 
                            'create_venv': 'venv_name', 'activate_venv': 'venv_name'}
            if command_name in arg_name_map:
                args_dict[arg_name_map[command_name]] = parts[1]

        # Use the primary BDI integration point to execute the command
        result = await coder.execute(**args_dict)
        
        # Pretty-print the JSON-like dictionary result
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    # This allows the file to be run directly for testing.
    # e.g., `python -m tools.simple_coder` from the project root.
    try:
        asyncio.run(main_cli())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
