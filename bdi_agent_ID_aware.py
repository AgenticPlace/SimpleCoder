# core/bdi_agent.py (Version 3.1 - Identity-Aware Constructor)
"""
This module defines the core of the BDI (Belief-Desire-Intention) agent.
It orchestrates the agent's perception-deliberation-action cycle, managing
its beliefs, goals (desires), and plans (intentions).

This version is updated to accept an identity record upon instantiation,
ensuring an agent is "born" with its identity rather than creating it itself.
This is a critical security and architectural pattern for the SIO.
"""
from __future__ import annotations
import asyncio
import json
import importlib
import uuid
import time
from enum import Enum, auto
from typing import Dict, List, Any, Optional, Tuple, Callable, Awaitable

# Assuming these are actual, well-defined modules in the project structure
from utils.config import Config
from utils.logging_config import get_logger
from llm.llm_factory import create_llm_handler
from llm.llm_interface import LLMHandlerInterface
from .belief_system import BeliefSystem, BeliefSource

logger = get_logger(__name__)

# --- Formal State Machines for Clarity and Robustness ---

class AgentStatus(Enum):
    """Defines the explicit lifecycle states of the BDI agent."""
    UNINITIALIZED = auto()
    INITIALIZED = auto()
    RUNNING = auto()
    PLANNING = auto()
    EXECUTING_ACTION = auto()
    IDLE_COMPLETE = auto()      # Completed all goals and is now idle
    GOAL_ACHIEVED = auto()      # Completed its primary goal
    FAILED_INITIALIZATION = auto()
    FAILED_PLANNING = auto()
    FAILED_ACTION = auto()
    FAILED_UNRECOVERABLE = auto()
    TIMED_OUT = auto()

class PlanStatus(Enum):
    """Defines the status of the current intention/plan."""
    NONE = auto()
    READY = auto()
    EXECUTING = auto()
    COMPLETED = auto()
    FAILED = auto()

class BaseTool:
    """Abstract base class for all tools available to the BDI agent."""
    def __init__(self,
                 config: Optional[Config] = None,
                 llm_handler: Optional[LLMHandlerInterface] = None,
                 bdi_agent_ref: Optional['BDIAgent'] = None,
                 **kwargs: Any):
        self.config = config or Config()
        self.llm_handler = llm_handler
        self.bdi_agent_ref = bdi_agent_ref
        self.logger = get_logger(f"tool.{self.__class__.__name__}")

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Executes the tool's primary function.
        MUST return a dictionary with at least a 'status': 'SUCCESS'|'ERROR'|'FAILURE' key.
        """
        raise NotImplementedError(f"Tool execute method not implemented for {self.__class__.__name__}.")

class BDIAgent:
    """
    Implements the Belief-Desire-Intention (BDI) architecture for a tactical,
    autonomous agent. It receives goals from a higher-level agent and is
    responsible for planning and executing the steps to achieve them.
    """
    def __init__(self,
                 domain: str,
                 identity: Dict[str, Any], # MODIFICATION: Identity is now a required parameter
                 belief_system: BeliefSystem,
                 tools_config: Dict,
                 initial_goal: Optional[str] = None,
                 config: Optional[Config] = None,
                 test_mode: bool = False):
        """
        Initializes the BDIAgent. It must be provided with an identity
        by its creator (e.g., MastermindAgent).

        Args:
            domain: A string defining the agent's area of expertise or purpose.
            identity: A dictionary containing the agent's public identity record,
                      provisioned by the IDManagerAgent.
            belief_system: An instance of the BeliefSystem for this agent.
            tools_config: A dictionary (often the full tools registry) defining
                          the tools this agent is permitted to use.
            initial_goal: An optional initial goal for the agent to pursue.
            config: An optional Config object.
            test_mode: A boolean flag for testing purposes.
        """
        # --- MODIFICATION: Agent ID and identity are derived from the injected record ---
        self.identity = identity
        self.agent_id = identity.get("entity_id", domain) # Use entity_id as the primary agent_id
        self.public_address = identity.get("public_address")
        
        self.logger = get_logger(f"bdi_agent.{self.agent_id}")
        self.domain = domain
        self.config = config or Config()
        self.belief_system = belief_system
        self.tools_config = tools_config
        self.test_mode = test_mode

        # Core BDI components
        self.desires: Dict[str, Any] = {"primary_goal": None, "queue": []}
        self.intentions: Dict[str, Any] = {"plan_id": None, "actions": [], "status": PlanStatus.NONE, "goal_id": None}
        
        # State and tools
        self.status = AgentStatus.UNINITIALIZED
        self.llm_handler: Optional[LLMHandlerInterface] = None
        self.available_tools: Dict[str, BaseTool] = {}
        self._action_handlers: Dict[str, Callable] = self._get_action_handlers()
        
        if initial_goal:
            self.set_primary_goal(initial_goal)
            
        self.logger.info(f"Agent {self.agent_id} (Address: {self.public_address[:10] if self.public_address else 'N/A'}...) initialized synchronously.")

    async def async_init(self) -> bool:
        """Initializes asynchronous components like the LLM and tools."""
        if self.status != AgentStatus.UNINITIALIZED:
            return True
            
        self.logger.info(f"Starting asynchronous component initialization for {self.agent_id}...")
        try:
            self.llm_handler = await create_llm_handler()
            if not self.llm_handler:
                raise RuntimeError("LLM Handler creation failed for BDI agent.")
            self.logger.info(f"LLM Handler initialized for {self.agent_id}: {self.llm_handler.provider_name}")

            await self._initialize_tools()
            
            self.status = AgentStatus.INITIALIZED
            self.logger.info(f"Agent {self.agent_id} fully initialized. Tools loaded: {list(self.available_tools.keys())}")
            return True
        except Exception as e:
            self.logger.critical(f"CRITICAL: Failed to initialize components for {self.agent_id}: {e}", exc_info=True)
            self.status = AgentStatus.FAILED_INITIALIZATION
            return False

    async def _initialize_tools(self):
        """Loads and initializes tools specified in the tools configuration."""
        self.logger.info("Initializing tools...")
        for tool_id, tool_info in self.tools_config.get("registered_tools", {}).items():
            if not tool_info.get("enabled", False):
                continue
            try:
                module_path, class_name = tool_info["module_path"], tool_info["class_name"]
                module = importlib.import_module(module_path)
                ToolClass = getattr(module, class_name)
                # Pass necessary components to the tool instance
                self.available_tools[tool_id] = ToolClass(
                    config=self.config,
                    llm_handler=self.llm_handler,
                    bdi_agent_ref=self
                )
                self.logger.info(f"Successfully loaded tool for {self.agent_id}: {tool_id} ({class_name})")
            except Exception as e:
                self.logger.error(f"Failed to load tool '{tool_id}' for {self.agent_id}: {e}", exc_info=True)

    def _get_action_handlers(self) -> Dict[str, Callable]:
        """Centralizes action dispatching logic."""
        return {
            # Meta/Cognitive Actions
            "THINK": self._action_think,
            "DECOMPOSE_GOAL": self._action_llm_cognitive,
            "ANALYZE_FAILURE": self._action_llm_cognitive,
            "UPDATE_BELIEF": self._action_update_belief,
            "NO_OP": self._action_no_op,
            "FAIL": self._action_fail,
            # Tool Actions
            "EXECUTE_TOOL": self._action_execute_tool,
        }

    async def run(self, max_cycles: int = 50) -> AgentStatus:
        """The main BDI execution loop, orchestrating the agent's lifecycle."""
        if self.status == AgentStatus.UNINITIALIZED and not await self.async_init():
            return self.status

        self.status = AgentStatus.RUNNING
        self.logger.info(f"Starting BDI run for {self.agent_id}. Max cycles: {max_cycles}")

        for cycle_count in range(1, max_cycles + 1):
            log_prefix = f"Cycle {cycle_count}/{max_cycles}"
            self.logger.info(f"--- {log_prefix} | Status: {self.status.name} ---")
            
            try:
                goal_to_pursue = self._deliberate()
                if not goal_to_pursue:
                    self.status = AgentStatus.IDLE_COMPLETE
                    break

                if self.intentions["goal_id"] != goal_to_pursue["id"]:
                    self.status = AgentStatus.PLANNING
                    if not await self._plan(goal_to_pursue):
                        self.status = AgentStatus.FAILED_PLANNING
                        break

                if self.intentions["status"] == PlanStatus.READY:
                    self.status = AgentStatus.EXECUTING_ACTION
                    if not await self._execute_intention():
                        self.status = AgentStatus.FAILED_ACTION
                        break
                
                if self.intentions["status"] == PlanStatus.COMPLETED:
                    self._mark_goal_as_complete(goal_to_pursue["id"])
                    if goal_to_pursue.get("is_primary"):
                        self.status = AgentStatus.GOAL_ACHIEVED
                        break
            
            except Exception as e:
                self.logger.critical(f"Unhandled exception in BDI cycle for {self.agent_id}: {e}", exc_info=True)
                self.status = AgentStatus.FAILED_UNRECOVERABLE
                break

            await asyncio.sleep(self.config.get("bdi.cycle_delay_seconds", 0.1))

        if self.status == AgentStatus.RUNNING:
            self.status = AgentStatus.TIMED_OUT
            
        self.logger.info(f"BDI run for {self.agent_id} finished with final status: {self.status.name}")
        return self.status

    def _deliberate(self) -> Optional[Dict[str, Any]]:
        """Selects the highest-priority, pending goal."""
        for goal in self.desires["queue"]:
            if goal.get("status") == "pending":
                self.logger.info(f"Deliberation: Selected goal '{goal['goal']}'")
                return goal
        return None

    async def _plan(self, goal: Dict[str, Any]) -> bool:
        """Generates and validates a plan to achieve the given goal."""
        self.logger.info(f"Generating plan for goal: {goal['goal']}")
        plan_generation_prompt = self._get_planning_prompt(goal)
        try:
            response_str = await self.llm_handler.generate_text(plan_generation_prompt, temperature=0.1, json_mode=True)
            raw_plan = json.loads(response_str)
        except Exception as e:
            self.logger.error(f"LLM plan generation failed: {e}", exc_info=True)
            return False

        is_valid, validation_error = self._validate_plan(raw_plan)
        if not is_valid:
            self.logger.error(f"Generated plan is invalid: {validation_error}")
            return False

        self._set_intention(raw_plan, goal["id"])
        return True

    def _get_planning_prompt(self, goal: Dict[str, Any]) -> str:
        """Constructs the prompt for the LLM to generate a plan."""
        available_actions_str = ", ".join(sorted(self._action_handlers.keys()))
        tools_manifest = [f"- {name}: {tool.__class__.__doc__.strip().splitlines()[0] if tool.__class__.__doc__ else 'No description.'}" for name, tool in self.available_tools.items()]
        tools_list_str = "\n".join(tools_manifest) or "No external tools available."
        
        return (
            f"You are a meticulous AI planning assistant for agent '{self.agent_id}' in domain '{self.domain}'.\n"
            f"Primary Goal: \"{goal['goal']}\"\n\n"
            f"Generate a step-by-step plan. You MUST use ONLY these action types:\n{available_actions_str}\n\n"
            f"If an action requires an external tool (like file operations), you MUST use the `EXECUTE_TOOL` action. "
            f"The `params` for `EXECUTE_TOOL` must include a `tool_id` (e.g., 'simple_coder') and a `command` key specifying the tool's sub-command (e.g., 'ls', 'write').\n"
            f"Available tools:\n{tools_list_str}\n\n"
            f"Respond ONLY with a valid JSON list of action dictionaries. Each action must have 'type' and 'params' keys."
        )

    def _validate_plan(self, plan: Any) -> Tuple[bool, Optional[str]]:
        """Validates the structure and content of a plan from the LLM."""
        if not isinstance(plan, list) or not plan:
            return False, "Plan must be a non-empty list."
            
        for i, step in enumerate(plan):
            if not isinstance(step, dict) or "type" not in step or "params" not in step:
                return False, f"Step {i+1} is malformed (missing 'type' or 'params')."
            
            action_type = step["type"]
            if action_type not in self._action_handlers:
                return False, f"Step {i+1} uses invalid action type '{action_type}'."

            if action_type == "EXECUTE_TOOL":
                params = step["params"]
                if "tool_id" not in params: return False, f"Step {i+1} EXECUTE_TOOL is missing 'tool_id'."
                if params["tool_id"] not in self.available_tools: return False, f"Step {i+1} references unavailable tool '{params['tool_id']}'."
                if "command" not in params: return False, f"Step {i+1} EXECUTE_TOOL is missing 'command'."
                    
        return True, None

    async def _execute_intention(self) -> bool:
        """Executes the next action in the current plan."""
        if self.intentions["status"] != PlanStatus.READY or not self.intentions["actions"]:
            return True

        action = self.intentions["actions"][0]
        action_type, params = action["type"], action["params"]
        handler = self._action_handlers.get(action_type)

        self.logger.info(f"Executing action '{action_type}' with params: {str(params)[:200]}")
        
        try:
            success, result = await handler(params)
            await self._on_action_completed(action, success, result)
            return success
        except Exception as e:
            self.logger.error(f"Unhandled exception during action '{action_type}': {e}", exc_info=True)
            await self._on_action_completed(action, False, f"Unhandled exception: {e}")
            return False

    async def _on_action_completed(self, action: Dict, success: bool, result: Any):
        """Updates agent state after an action is completed."""
        self.intentions["actions"].pop(0)

        if success:
            self.logger.info(f"Action '{action['type']}' SUCCEEDED. Result: {str(result)[:150]}...")
            if not self.intentions["actions"]:
                self.intentions["status"] = PlanStatus.COMPLETED
        else:
            self.logger.error(f"Action '{action['type']}' FAILED. Reason: {result}")
            self.intentions["status"] = PlanStatus.FAILED

    # --- Action Handler Implementations ---

    async def _action_think(self, params: Dict) -> Tuple[bool, str]:
        thought = params.get("thought", "No thought provided.")
        self.logger.info(f"Agent Thought: {thought}")
        return True, "Thought processed."
        
    async def _action_execute_tool(self, params: Dict) -> Tuple[bool, Any]:
        tool_id = params.get("tool_id")
        if not tool_id: return False, "EXECUTE_TOOL action requires a 'tool_id'."
        
        tool = self.available_tools.get(tool_id)
        if not tool: return False, f"Tool '{tool_id}' not available."
        
        try:
            # The tool's execute method now receives the full params dict,
            # which includes the 'command' it needs to dispatch internally.
            result = await tool.execute(**params)
            if not isinstance(result, dict) or "status" not in result:
                self.logger.warning(f"Tool '{tool_id}' returned a non-standard result: {result}")
                return False, f"Tool '{tool_id}' returned malformed output."
            
            return result.get("status") == "SUCCESS", result
        except Exception as e:
            self.logger.error(f"Exception while executing tool '{tool_id}': {e}", exc_info=True)
            return False, {"status": "ERROR", "message": f"Exception in tool: {e}"}

    async def _action_llm_cognitive(self, params: Dict) -> Tuple[bool, Any]:
        prompt = params.get("prompt", "Perform a cognitive task.")
        try:
            return True, await self.llm_handler.generate_text(prompt)
        except Exception as e:
            return False, f"LLM call failed: {e}"

    async def _action_update_belief(self, params: Dict) -> Tuple[bool, Any]:
        key, value = params.get("key"), params.get("value")
        if key is None or value is None: return False, "Missing 'key' or 'value'."
        await self.belief_system.add_belief(key, value, 1.0, BeliefSource.SELF_INFERENCE)
        return True, f"Belief '{key}' updated."
        
    async def _action_no_op(self, params: Dict) -> Tuple[bool, Any]:
        return True, "No operation performed."

    async def _action_fail(self, params: Dict) -> Tuple[bool, Any]:
        return False, params.get('reason', 'Intentional failure specified in plan.')

    # --- Public Interface & State Management ---

    def set_primary_goal(self, goal_description: str):
        """Sets the main goal for the agent to achieve."""
        goal_id = f"primary_{uuid.uuid4().hex[:6]}"
        new_goal = {"id": goal_id, "goal": goal_description, "priority": 100, "status": "pending", "added_at": time.time(), "is_primary": True}
        self.desires["primary_goal"] = new_goal
        self.desires["queue"] = [g for g in self.desires["queue"] if not g.get("is_primary")]
        self.desires["queue"].append(new_goal)
        self.desires["queue"].sort(key=lambda g: (-g["priority"], g["added_at"]))
        self.logger.info(f"Set primary goal: {goal_description}")

    def _set_intention(self, plan: List[Dict], goal_id: str):
        """Sets the agent's current plan of action."""
        plan_id = f"plan_{uuid.uuid4().hex[:6]}"
        for i, action in enumerate(plan):
            action["id"] = f"act_{plan_id}_{i+1}"
        
        self.intentions = {"plan_id": plan_id, "actions": plan, "status": PlanStatus.READY, "goal_id": goal_id}
        self.logger.info(f"Set new intention (Plan ID: {plan_id}) with {len(plan)} actions for goal '{goal_id}'.")

    def _mark_goal_as_complete(self, goal_id: str):
        """Marks a goal in the desire queue as completed."""
        for goal in self.desires["queue"]:
            if goal["id"] == goal_id:
                goal["status"] = "completed"
                break
        self.intentions = {"plan_id": None, "actions": [], "status": PlanStatus.NONE, "goal_id": None}

    async def shutdown(self):
        """Placeholder for any future agent cleanup logic."""
        self.logger.info(f"Agent {self.agent_id} shutting down.")
