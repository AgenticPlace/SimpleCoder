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
import copy
import stat
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable, Awaitable, Union

# Assuming these are actual, well-defined modules
from utils.config import Config, PROJECT_ROOT
from utils.logging_config import get_logger
logger = get_logger(__name__)

from core.belief_system import BeliefSystem, BeliefSource
from llm.llm_interface import LLMHandlerInterface
from llm.llm_factory import create_llm_handler
from core.bdi_agent import BDIAgent, BaseTool as BDIBaseTool, AgentStatus as BDIAgentStatus
from core.id_manager_agent import IDManagerAgent
from .coordinator_agent import CoordinatorAgent, InteractionType, InteractionStatus, Interaction
import importlib

# Stubs for type hinting if imports fail in a minimal environment
try:
    from tools.base_gen_agent import BaseGenAgent
except ImportError:
    class BaseGenAgent: pass # Dummy class if not found

class StrategicCampaign:
    """
    A data class to formalize the concept of a Mastermind-led campaign.
    This tracks the state and outcome of a high-level strategic initiative.
    """
    def __init__(self, directive: str, campaign_type: str = "SYSTEM_EVOLUTION"):
        self.id = f"mscamp_{uuid.uuid4().hex[:8]}"
        self.directive = directive
        self.type = campaign_type
        self.status = "PENDING"
        self.created_at = time.time()
        self.completed_at: Optional[float] = None
        self.outcome: Optional[Dict[str, Any]] = None
        self.sub_tasks: List[Dict[str, Any]] = []

    def to_dict(self):
        """Serializes the campaign object to a dictionary for logging."""
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
                # Pass all kwargs to the constructor
                cls._instance = cls(**kwargs)
                await cls._instance._async_init_components()
            return cls._instance

    def __init__(self,
                 agent_id: str = "mastermind_prime",
                 config_override: Optional[Config] = None,
                 belief_system_instance: Optional[BeliefSystem] = None,
                 coordinator_agent_instance: Optional[CoordinatorAgent] = None,
                 test_mode: bool = False,
                 **kwargs):
        """Initializes the Mastermind agent's synchronous components."""
        if hasattr(self, '_initialized_sync') and self._initialized_sync and not test_mode:
            return
            
        self.agent_id = agent_id
        self.config: Config = config_override or Config(test_mode=test_mode)
        self.belief_system: BeliefSystem = belief_system_instance or BeliefSystem(test_mode=test_mode)
        self.coordinator_agent: Optional[CoordinatorAgent] = coordinator_agent_instance
        self.test_mode = test_mode
        
        self.log_prefix = f"Mastermind ({self.agent_id}):"
        self.logger = get_logger(f"mastermind.{self.agent_id}")
        
        self.data_dir = PROJECT_ROOT / self.config.get("mastermind_agent.data_dir", f"data/mastermind_work/{self.agent_id}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # --- State and Registries ---
        self.tools_registry_path = PROJECT_ROOT / self.config.get("mastermind_agent.tools_registry_path", "data/config/official_tools_registry.json")
        self.tools_registry = self._load_json(self.tools_registry_path, {"registered_tools": {}})
        self.campaign_history = self._load_json(self.data_dir / "mastermind_campaign_history.json", [])
        
        # --- Core Components ---
        self.llm_handler: Optional[LLMHandlerInterface] = None
        self.bdi_agent = BDIAgent(
            domain=f"mastermind_strategy.{self.agent_id}",
            belief_system=self.belief_system,
            tools_config=self.tools_registry,
            config=self.config,
            test_mode=self.test_mode
        )
        self.code_base_analyzer: Optional[BaseGenAgent] = self._init_code_analyzer()
        
        self._register_mastermind_bdi_actions()
        self.autonomous_loop_task: Optional[asyncio.Task] = None
        self._initialized_sync = True
        self._initialized_async = False
        self.logger.info(f"{self.log_prefix} Synchronous initialization complete.")


    async def _async_init_components(self):
        """Initializes asynchronous components like LLMs and subordinate agents."""
        if self._initialized_async and not self.test_mode: return
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
            
        self._initialized_async = True
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
            # Perception & Assessment
            "OBSERVE_SYSTEM_STATE": self._bdi_observe_system_state,
            "ASSESS_TOOL_SUITE": self._bdi_assess_tool_suite,
            "ANALYZE_CODEBASE": self._bdi_analyze_codebase,
            # Strategy & Planning
            "PROPOSE_STRATEGY": self._bdi_propose_strategy,
            "CONCEPTUALIZE_NEW_TOOL": self._bdi_conceptualize_new_tool,
            # Action & Execution
            "INITIATE_DEVELOPMENT_TASK": self._bdi_initiate_development_task,
            "REGISTER_TOOL": self. _bdi_register_tool,
            "DEPRECATE_TOOL": self._bdi_deprecate_tool,
        }
        # This safely updates the BDI agent's handlers
        self.bdi_agent._action_handlers.update(bdi_actions)
        self.logger.info(f"{self.log_prefix} Injected {len(bdi_actions)} specialized actions into subordinate BDI agent.")

    async def launch_campaign(self, directive: str, max_bdi_cycles: int = 25) -> Dict[str, Any]:
        """
        Public method to start a new strategic campaign. This is the primary
        entry point for commanding the Mastermind.
        """
        if not self._initialized_async: await self._async_init_components()

        campaign = StrategicCampaign(directive=directive)
        self.logger.info(f"{self.log_prefix} Launching new campaign '{campaign.id}': {directive}")

        self.bdi_agent.set_primary_goal(
            f"Fulfill Mastermind campaign '{campaign.id}': {directive}"
        )
        final_bdi_status = await self.bdi_agent.run(max_cycles=max_bdi_cycles)

        campaign.status = "COMPLETED" if final_bdi_status == BDIAgentStatus.GOAL_ACHIEVED else "FAILED_INCOMPLETE"
        campaign.completed_at = time.time()
        campaign.outcome = {
            "final_bdi_status": final_bdi_status.name,
            # A real implementation would pull detailed results from the belief system
            "summary": f"Campaign concluded with status {final_bdi_status.name}."
        }
        
        self.campaign_history.append(campaign.to_dict())
        self._save_json(self.data_dir / "mastermind_campaign_history.json", self.campaign_history)
        
        self.logger.info(f"{self.log_prefix} Campaign '{campaign.id}' finished with status: {campaign.status}")
        return campaign.to_dict()

    # --- BDI Action Implementations ---

    async def _bdi_observe_system_state(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Gathers high-level system state from the Coordinator."""
        self.logger.info(f"{self.log_prefix} BDI Action: Observing system state via Coordinator.")
        if not self.coordinator_agent: return False, {"error": "CoordinatorAgent not available."}
        
        interaction = await self.coordinator_agent.create_interaction(
            interaction_type=InteractionType.SYSTEM_ANALYSIS,
            content="Mastermind request: Provide a high-level system health and status summary.",
            agent_id=self.agent_id
        )
        processed_interaction = await self.coordinator_agent.process_interaction(interaction)
        
        if processed_interaction.status == InteractionStatus.COMPLETED:
            return True, processed_interaction.response
        else:
            return False, {"error": f"Failed to get summary: {processed_interaction.error}"}

    async def _bdi_assess_tool_suite(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Performs a qualitative assessment of the current tool suite."""
        self.logger.info(f"{self.log_prefix} BDI Action: Assessing tool suite.")
        if not self.llm_handler: return False, {"error": "Mastermind LLM not available."}

        tools_summary = [{"id": tid, "desc": t.get("description", ""), "status": t.get("status")} for tid, t in self.tools_registry.get("registered_tools", {}).items()]
        prompt = "Assess the system's tool suite for gaps, redundancies, and opportunities based on this list:\n" + json.dumps(tools_summary, indent=2) + "\nRespond with JSON: {\"summary\": \"...\", \"gaps\": [...], \"redundancies\": [...]}"
        
        try:
            response_str = await self.llm_handler.generate_text(prompt, json_mode=True)
            return True, json.loads(response_str)
        except Exception as e:
            return False, {"error": f"LLM tool assessment failed: {e}"}

    async def _bdi_propose_strategy(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Based on an assessment, propose a concrete strategy."""
        assessment = params.get("assessment")
        if not assessment: return False, {"error": "Tool assessment data is required."}
        
        prompt = "Given this assessment, propose a list of strategic actions (e.g., 'CONCEPTUALIZE_NEW_TOOL', 'DEPRECATE_TOOL').\n" + f"Assessment:\n{json.dumps(assessment, indent=2)}\n\n" + "Respond with JSON: {\"recommendations\": [{\"action\": \"...\", \"target\": \"...\", \"justification\": \"...\"}]}"
        try:
            response_str = await self.llm_handler.generate_text(prompt, json_mode=True)
            return True, json.loads(response_str)
        except Exception as e:
            return False, {"error": f"LLM strategy proposal failed: {e}"}
            
    async def _bdi_conceptualize_new_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Generates a detailed specification for a new tool."""
        need = params.get("identified_need", "a tool to address a strategic gap.")
        self.logger.info(f"{self.log_prefix} BDI Action: Conceptualizing new tool for need: {need}")
        
        prompt = f"Design a new tool specification to address this need: '{need}'. Respond with a detailed JSON object including 'tool_id', 'description', 'module_path', 'class_name', and a list of 'capabilities' with schemas."
        try:
            response_str = await self.llm_handler.generate_text(prompt, max_tokens=2048, json_mode=True)
            tool_concept = json.loads(response_str)
            if not all(k in tool_concept for k in ["tool_id", "description", "capabilities"]):
                raise ValueError("Generated concept is missing required keys.")
            return True, tool_concept
        except Exception as e:
            return False, {"error": f"LLM tool conceptualization failed: {e}"}

    async def _bdi_initiate_development_task(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Sends a development task to the Coordinator for the SIA."""
        tool_concept = params.get("tool_concept")
        if not tool_concept: return False, {"error": "Tool concept specification is required."}
        self.logger.info(f"{self.log_prefix} BDI Action: Initiating development for tool '{tool_concept.get('tool_id')}' via Coordinator.")
        if not self.coordinator_agent: return False, {"error": "CoordinatorAgent not available."}

        content = f"Mastermind directive: Initiate development for tool '{tool_concept.get('tool_id')}'."
        metadata = {"target_component": tool_concept.get('module_path'), "analysis_context": json.dumps(tool_concept)}
        interaction = await self.coordinator_agent.create_interaction(InteractionType.COMPONENT_IMPROVEMENT, content, agent_id=self.agent_id, metadata=metadata)
        processed_interaction = await self.coordinator_agent.process_interaction(interaction)
        
        if processed_interaction.status == InteractionStatus.COMPLETED and processed_interaction.response.get("status") == "SUCCESS":
            return True, {"message": "SIA successfully tasked for tool development.", "sia_response": processed_interaction.response}
        else:
            return False, {"error": f"SIA tasking failed: {processed_interaction.error or processed_interaction.response}"}

    async def _bdi_register_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Adds or updates a tool's definition in the official registry."""
        tool_definition = params.get("tool_definition")
        if not isinstance(tool_definition, dict) or "tool_id" not in tool_definition: return False, {"error": "A valid tool definition with 'tool_id' is required."}
        
        tool_id = tool_definition["tool_id"]
        self.tools_registry.setdefault("registered_tools", {})[tool_id] = tool_definition
        self._save_json(self.tools_registry_path, self.tools_registry)
        return True, {"message": f"Tool '{tool_id}' registered/updated."}

    async def _bdi_deprecate_tool(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Marks a tool as deprecated in the registry."""
        tool_id, reason = params.get("tool_id"), params.get("reason", "No reason provided.")
        if not tool_id or tool_id not in self.tools_registry.get("registered_tools", {}): return False, {"error": f"Tool '{tool_id}' not found."}

        self.tools_registry["registered_tools"][tool_id]["status"] = "deprecated"
        self.tools_registry["registered_tools"][tool_id]["deprecation_reason"] = reason
        self._save_json(self.tools_registry_path, self.tools_registry)
        return True, {"message": f"Tool '{tool_id}' marked as deprecated."}

    async def _bdi_analyze_codebase(self, params: Dict) -> Tuple[bool, Any]:
        """BDI Action: Uses the CodeBaseGenerator to analyze a repo."""
        if not self.code_base_analyzer: return False, {"error": "CodeBaseGenerator not available."}
        target_path = params.get("target_path")
        if not target_path: return False, {"error": "'target_path' is required."}

        try:
            summary = self.code_base_analyzer.generate_markdown_summary(str(target_path))
            return True, {"summary": summary, "message": "Analysis complete."}
        except Exception as e:
            return False, {"error": f"Codebase analysis failed: {e}"}

    # --- Helper & Lifecycle Methods ---

    def start_autonomous_loop(self, interval: Optional[float] = None):
        """Starts the main autonomous evolution loop."""
        if self.autonomous_loop_task and not self.autonomous_loop_task.done(): return
        loop_interval = interval or self.config.get("mastermind_agent.autonomous_loop.interval_seconds", 3600.0)
        directive = self.config.get("mastermind_agent.autonomous_loop.default_directive", "Proactively evolve the MindX system.")
        self.autonomous_loop_task = asyncio.create_task(self._autonomous_worker(loop_interval, directive))
        self.logger.info(f"{self.log_prefix} Autonomous evolution loop started. Interval: {loop_interval}s.")

    async def _autonomous_worker(self, interval: float, directive: str):
        """The background task that periodically triggers a strategic campaign."""
        while True:
            try:
                await asyncio.sleep(interval)
                self.logger.info(f"{self.log_prefix} Autonomous worker initiating strategic cycle.")
                await self.launch_campaign(directive)
            except asyncio.CancelledError:
                self.logger.info(f"{self.log_prefix} Autonomous worker stopping."); break
            except Exception as e:
                self.logger.error(f"{self.log_prefix} Unhandled error in autonomous worker loop: {e}", exc_info=True)

    async def shutdown(self):
        """Gracefully shuts down the Mastermind agent."""
        self.logger.info(f"{self.log_prefix} Shutting down...")
        if self.autonomous_loop_task and not self.autonomous_loop_task.done():
            self.autonomous_loop_task.cancel()
            try: await self.autonomous_loop_task
            except asyncio.CancelledError: pass
        if self.bdi_agent: await self.bdi_agent.shutdown()
        self._save_json(self.data_dir / "mastermind_campaign_history.json", self.campaign_history)
        self._save_json(self.tools_registry_path, self.tools_registry)
        self.logger.info(f"{self.log_prefix} Shutdown complete.")

    def _load_json(self, path: Path, default: Union[List, Dict]) -> Union[List, Dict]:
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f: return json.load(f)
            except Exception as e: self.logger.error(f"Error loading {path}: {e}")
        return copy.deepcopy(default)
    
    def _save_json(self, path: Path, data: Union[List, Dict]):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except Exception as e: self.logger.error(f"Error saving to {path}: {e}")
