# orchestration/mastermind_agent.py (Version 2.0 - Hardened Strategic Core)
"""
This module defines the MastermindAgent, the apex orchestrator of the MindX
Sovereign Intelligent Organization (SIO).

As the "Soul" of the system, its purpose is not to execute tasks, but to set
the strategic direction. It operates on a long-term horizon, initiating
"campaigns" for its subordinate agents to carry out. Its most critical function
is driving the evolution of the SIO itself by assessing its own capabilities,
conceptualizing new tools, and orchestrating their development and integration.
"""
from __future__ import annotations
import asyncio
import json
import time
import uuid
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

# Assuming these are actual, well-defined modules
from utils.config import Config, PROJECT_ROOT
from utils.logging_config import get_logger
logger = get_logger(__name__)

from core.belief_system import BeliefSystem, BeliefSource
from llm.llm_interface import LLMHandlerInterface
from llm.llm_factory import create_llm_handler
from core.bdi_agent import BDIAgent
from .coordinator_agent import CoordinatorAgent, InteractionType, InteractionStatus
# Import tool stubs for type hinting
try:
    from tools.base_gen_agent import BaseGenAgent
except ImportError:
    class BaseGenAgent: pass # Dummy class if not found

class StrategicCampaign:
    """A data class to formalize the concept of a Mastermind-led campaign."""
    def __init__(self, directive: str, campaign_type: str = "EVOLUTION"):
        self.id = f"mscamp_{uuid.uuid4().hex[:8]}"
        self.directive = directive
        self.type = campaign_type
        self.status = "PENDING"
        self.created_at = time.time()
        self.completed_at: Optional[float] = None
        self.outcome: Optional[Dict[str, Any]] = None
        self.sub_tasks: List[Dict[str, Any]] = []

    def to_dict(self):
        return self.__dict__

class MastermindAgent:
    """The apex agent responsible for strategic direction and system evolution."""
    _instance: Optional['MastermindAgent'] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls, **kwargs) -> 'MastermindAgent':
        """Singleton factory to get or create the Mastermind instance."""
        async with cls._lock:
            if cls._instance is None or kwargs.get("test_mode"):
                if kwargs.get("test_mode") and cls._instance is not None:
                    await cls._instance.shutdown()
                cls._instance = cls(**kwargs)
                await cls._instance._async_init_components()
            return cls._instance

    def __init__(self, agent_id: str = "mastermind_prime", **kwargs):
        """Initializes the Mastermind agent's synchronous components."""
        self.agent_id = agent_id
        self.config: Config = kwargs.get("config_override") or Config()
        self.belief_system: BeliefSystem = kwargs.get("belief_system_instance") or BeliefSystem()
        self.coordinator_agent: Optional[CoordinatorAgent] = kwargs.get("coordinator_agent_instance")
        self.test_mode = kwargs.get("test_mode", False)
        
        self.log_prefix = f"Mastermind ({self.agent_id}):"
        self.logger = get_logger(f"mastermind.{self.agent_id}")
        
        self.data_dir = PROJECT_ROOT / self.config.get("mastermind_agent.data_dir", f"data/mastermind_work/{self.agent_id}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # --- State and Registries ---
        self.tools_registry = self._load_json("official_tools_registry.json", {"registered_tools": {}})
        self.campaign_history = self._load_json("mastermind_campaign_history.json", [])
        self.strategic_objectives = self._load_json("mastermind_objectives.json", [])
        
        # --- Core Components ---
        self.llm_handler: Optional[LLMHandlerInterface] = None
        self.bdi_agent = BDIAgent(
            domain=f"mastermind_strategy.{self.agent_id}",
            belief_system=self.belief_system,
            tools_config=self.tools_registry, # The BDI uses the official tool registry
            config=self.config,
            test_mode=self.test_mode
        )
        self.code_base_analyzer: Optional[BaseGenAgent] = self._init_code_analyzer()
        
        self._register_mastermind_bdi_actions()
        self.autonomous_loop_task: Optional[asyncio.Task] = None
        self._initialized = False
        self.logger.info(f"{self.log_prefix} Synchronous initialization complete.")

    async def _async_init_components(self):
        """Initializes asynchronous components like LLMs and subordinate agents."""
        if self._initialized and not self.test_mode: return
        self.logger.info(f"{self.log_prefix} Starting asynchronous initialization...")
        
        self.llm_handler = await create_llm_handler()
        if not self.llm_handler:
            self.logger.critical(f"{self.log_prefix} CRITICAL: Failed to initialize main LLM handler.")
        
        await self.bdi_agent.async_init()
        
        if not self.coordinator_agent and not self.test_mode:
            from .coordinator_agent import get_coordinator_agent_mindx_async
            self.coordinator_agent = await get_coordinator_agent_mindx_async(config_override=self.config)
            
        if self.config.get("mastermind_agent.autonomous_loop.enabled", False) and not self.test_mode:
            self.start_autonomous_loop()
            
        self._initialized = True
        self.logger.info(f"{self.log_prefix} Asynchronous initialization complete. Autonomous loop: {bool(self.autonomous_loop_task)}")

    def _init_code_analyzer(self) -> Optional[BaseGenAgent]:
        """Initializes the CodeBaseGenerator tool if available."""
        try:
            from tools.base_gen_agent import BaseGenAgent
            return BaseGenAgent(agent_id=f"code_analyzer_for_{self.agent_id}")
        except ImportError:
            self.logger.warning(f"{self.log_prefix} CodeBaseGenerator not found. Code analysis capabilities are disabled.")
            return None

    def _register_mastermind_bdi_actions(self):
        """Injects Mastermind-specific actions into its subordinate BDI agent."""
        bdi_actions = {
            "OBSERVE_SYSTEM_STATE": self._bdi_observe_system_state,
            "ASSESS_TOOL_SUITE": self._bdi_assess_tool_suite,
            "PROPOSE_TOOL_STRATEGY": self._bdi_propose_tool_strategy,
            "CONCEPTUALIZE_NEW_TOOL": self._bdi_conceptualize_new_tool,
            "INITIATE_TOOL_DEVELOPMENT": self._bdi_initiate_tool_development,
            "REGISTER_TOOL": self. _bdi_register_tool,
            "DEPRECATE_TOOL": self._bdi_deprecate_tool
        }
        self.bdi_agent._action_handlers.update(bdi_actions)
        self.logger.info(f"{self.log_prefix} Injected {len(bdi_actions)} specialized actions into subordinate BDI agent.")

    async def launch_campaign(self, directive: str, max_bdi_cycles: int = 20) -> Dict[str, Any]:
        """Public method to start a new strategic campaign."""
        if not self._initialized: await self._async_init_components()

        campaign = StrategicCampaign(directive=directive)
        self.logger.info(f"{self.log_prefix} Launching new campaign '{campaign.id}': {directive}")

        self.bdi_agent.set_primary_goal(
            f"Fulfill Mastermind campaign '{campaign.id}': {directive}"
        )
        final_bdi_status = await self.bdi_agent.run(max_cycles=max_bdi_cycles)

        campaign.status = "COMPLETED" if final_bdi_status == BDIAgentStatus.GOAL_ACHIEVED else "FAILED"
        campaign.completed_at = time.time()
        campaign.outcome = {
            "final_bdi_status": final_bdi_status.name,
            # In a real system, you'd pull more detailed results from the belief system
            "summary": f"Campaign concluded with status {final_bdi_status.name}."
        }
        
        self.campaign_history.append(campaign.to_dict())
        self._save_json("mastermind_campaign_history.json", self.campaign_history)
        
        self.logger.info(f"{self.log_prefix} Campaign '{campaign.id}' finished with status: {campaign.status}")
        return campaign.to_dict()

    # --- BDI Action Implementations ---
    # These methods are called BY the BDIAgent, acting on behalf of Mastermind.

    async def _bdi_observe_system_state(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Gathers high-level system state from the Coordinator."""
        self.logger.info(f"{self.log_prefix} BDI Action: Observing system state via Coordinator.")
        if not self.coordinator_agent: return False, "CoordinatorAgent not available."
        
        interaction = await self.coordinator_agent.create_interaction(
            interaction_type=InteractionType.SYSTEM_ANALYSIS,
            content="Mastermind request: Provide a high-level system health and status summary.",
            agent_id=self.agent_id
        )
        processed_interaction = await self.coordinator_agent.process_interaction(interaction)
        
        if processed_interaction.status == InteractionStatus.COMPLETED:
            return True, processed_interaction.response
        else:
            return False, f"Failed to get summary: {processed_interaction.error}"

    async def _bdi_assess_tool_suite(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Performs a qualitative assessment of the current tool suite."""
        self.logger.info(f"{self.log_prefix} BDI Action: Assessing tool suite.")
        if not self.llm_handler: return False, "Mastermind LLM not available."

        tools_summary = [
            {"id": tid, "desc": t.get("description", "N/A"), "status": t.get("status")}
            for tid, t in self.tools_registry.get("registered_tools", {}).items()
        ]
        
        prompt = (
            "You are a strategic AI architect. Based on the following list of available tools, "
            "provide a high-level assessment of the system's capabilities. Identify any obvious gaps, redundancies, "
            "or areas where tools seem experimental and might need hardening.\n\n"
            f"Tool Suite:\n{json.dumps(tools_summary, indent=2)}\n\n"
            "Respond with a JSON object: {\"assessment_summary\": \"...\", \"identified_gaps\": [...]}"
        )
        
        try:
            response_str = await self.llm_handler.generate_text(prompt, json_mode=True)
            assessment = json.loads(response_str)
            return True, assessment
        except Exception as e:
            return False, f"LLM tool assessment failed: {e}"

    async def _bdi_propose_tool_strategy(self, params: Dict) -> Tuple[bool, Any]:
        """
        BDI Action: Based on an assessment, propose a concrete strategy.
        IMPROVEMENT: This is now a separate, more focused cognitive step.
        """
        assessment = params.get("assessment")
        if not assessment: return False, "Tool assessment data is required."
        
        prompt = (
            "You are a strategic AI planner. Given the following assessment of the system's tool suite, "
            "propose a list of concrete strategic actions. Actions can be 'CONCEPTUALIZE_NEW_TOOL', "
            "'INITIATE_TOOL_ENHANCEMENT', or 'DEPRECATE_TOOL'.\n\n"
            f"Assessment:\n{json.dumps(assessment, indent=2)}\n\n"
            "Respond with a JSON object: {\"strategic_recommendations\": [{\"action_type\": \"...\", \"target\": \"...\", \"justification\": \"...\"}]}"
        )
        try:
            response_str = await self.llm_handler.generate_text(prompt, json_mode=True)
            return True, json.loads(response_str)
        except Exception as e:
            return False, f"LLM strategy proposal failed: {e}"

    async def _bdi_conceptualize_new_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Generates a detailed specification for a new tool."""
        need = params.get("identified_need", "a tool to address a strategic gap.")
        self.logger.info(f"{self.log_prefix} BDI Action: Conceptualizing new tool for need: {need}")
        
        # This prompt is highly detailed to get a structured, useful output from the LLM.
        prompt = (
            f"You are a tool designer for an AI system. Conceptualize a new tool to address this need: '{need}'.\n"
            "Define the tool's specification as a detailed JSON object with the following keys:\n"
            " - 'tool_id': A unique, Python-style identifier (e.g., 'code_documentation_generator_v1').\n"
            " - 'description': What the tool does.\n"
            " - 'module_path': Suggested Python module path (e.g., 'tools.documentation').\n"
            " - 'class_name': Suggested Python class name (e.g., 'CodeDocGeneratorTool').\n"
            " - 'capabilities': A list of key functions, each with 'name', 'description', and schemas for input/output.\n"
            " - 'initial_status': Set to 'under_development'."
        )
        try:
            response_str = await self.llm_handler.generate_text(prompt, max_tokens=2048, json_mode=True)
            tool_concept = json.loads(response_str)
            # Basic validation
            if not all(k in tool_concept for k in ["tool_id", "description", "capabilities"]):
                raise ValueError("Generated concept is missing required keys.")
            return True, tool_concept
        except Exception as e:
            return False, f"LLM tool conceptualization failed: {e}"

    async def _bdi_initiate_tool_development(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Sends a development task to the Coordinator."""
        tool_concept = params.get("tool_concept")
        if not tool_concept: return False, "Tool concept specification is required."
        
        self.logger.info(f"{self.log_prefix} BDI Action: Initiating development for tool '{tool_concept.get('tool_id')}' via Coordinator.")
        if not self.coordinator_agent: return False, "CoordinatorAgent not available."

        # The "content" is a structured request for the Coordinator's SIA to act upon.
        content = f"Mastermind directive: Initiate development for a new tool based on the provided specification. Target file is {tool_concept.get('module_path').replace('.', '/')}.py"
        metadata = {"target_component": tool_concept.get('module_path'), "analysis_context": json.dumps(tool_concept)}
        
        interaction = await self.coordinator_agent.create_interaction(
            interaction_type=InteractionType.COMPONENT_IMPROVEMENT,
            content=content, agent_id=self.agent_id, metadata=metadata
        )
        processed_interaction = await self.coordinator_agent.process_interaction(interaction)
        
        if processed_interaction.status == InteractionStatus.COMPLETED and processed_interaction.response.get("status") == "SUCCESS":
            return True, {"message": "SIA successfully tasked for tool development.", "sia_response": processed_interaction.response}
        else:

            return False, {"message": f"SIA tasking failed: {processed_interaction.error or processed_interaction.response}"}

    async def _bdi_register_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Adds or updates a tool's definition in the official registry."""
        tool_definition = params.get("tool_definition")
        if not isinstance(tool_definition, dict) or "tool_id" not in tool_definition:
            return False, "A valid tool definition dictionary with 'tool_id' is required."
        
        tool_id = tool_definition["tool_id"]
        self.tools_registry.setdefault("registered_tools", {})[tool_id] = tool_definition
        self._save_json("official_tools_registry.json", self.tools_registry)
        
        msg = f"Tool '{tool_id}' registered/updated in the official registry."
        self.logger.info(f"{self.log_prefix} {msg}")
        return True, {"message": msg, "tool_id": tool_id}

    async def _bdi_deprecate_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Marks a tool as deprecated in the registry."""
        tool_id = params.get("tool_id")
        reason = params.get("reason", "No reason provided.")
        
        if not tool_id or tool_id not in self.tools_registry.get("registered_tools", {}):
            return False, f"Tool '{tool_id}' not found in registry."

        self.tools_registry["registered_tools"][tool_id]["status"] = "deprecated"
        self.tools_registry["registered_tools"][tool_id]["deprecation_reason"] = reason
        self._save_json("official_tools_registry.json", self.tools_registry)

        msg = f"Tool '{tool_id}' marked as deprecated. Reason: {reason}"
        self.logger.info(f"{self.log_prefix} {msg}")
        return True, {"message": msg, "tool_id": tool_id}

    # --- Helper & Lifecycle Methods ---

    def start_autonomous_loop(self, interval: Optional[float] = None):
        """Starts the main autonomous evolution loop."""
        if self.autonomous_loop_task and not self.autonomous_loop_task.done():
            self.logger.warning(f"{self.log_prefix} Autonomous loop is already running.")
            return
        
        loop_interval = interval or self.config.get("mastermind_agent.autonomous_loop.interval_seconds", 3600.0)
        default_directive = self.config.get("mastermind_agent.autonomous_loop.default_directive", 
                                            "Proactively evolve the MindX system by assessing capabilities and orchestrating improvements.")
        
        self.autonomous_loop_task = asyncio.create_task(
            self._autonomous_worker(loop_interval, default_directive)
        )
        self.logger.info(f"{self.log_prefix} Autonomous evolution loop started. Interval: {loop_interval}s.")

    async def _autonomous_worker(self, interval: float, directive: str):
        """The background task that periodically triggers a strategic campaign."""
        self.logger.info(f"{self.log_prefix} Autonomous worker started.")
        while True:
            try:
                await asyncio.sleep(interval)
                self.logger.info(f"{self.log_prefix} Autonomous worker waking up to initiate strategic cycle.")
                await self.launch_campaign(directive)
            except asyncio.CancelledError:
                self.logger.info(f"{self.log_prefix} Autonomous worker stopping.")
                break
            except Exception as e:
                self.logger.error(f"{self.log_prefix} Unhandled error in autonomous worker loop: {e}", exc_info=True)
                # Avoid rapid failure loops by waiting for the full interval.
                await asyncio.sleep(interval)

    async def shutdown(self):
        """Gracefully shuts down the Mastermind agent and its components."""
        self.logger.info(f"{self.log_prefix} Shutting down...")
        if self.autonomous_loop_task and not self.autonomous_loop_task.done():
            self.autonomous_loop_task.cancel()
            try: await self.autonomous_loop_task
            except asyncio.CancelledError: pass
        if self.bdi_agent: await self.bdi_agent.shutdown()
        self._save_json("mastermind_campaign_history.json", self.campaign_history)
        self._save_json("mastermind_objectives.json", self.strategic_objectives)
        self._save_json("official_tools_registry.json", self.tools_registry)
        self.logger.info(f"{self.log_prefix} Shutdown complete.")

    def _load_json(self, filename: str, default: Union[List, Dict]) -> Union[List, Dict]:
        path = self.data_dir / filename
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f: return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.logger.error(f"Error loading {path}: {e}")
        return copy.deepcopy(default)
    
    def _save_json(self, filename: str, data: Union[List, Dict]):
        path = self.data_dir / filename
        try:
            with path.open('w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except OSError as e:
            self.logger.error(f"Error saving to {path}: {e}")
