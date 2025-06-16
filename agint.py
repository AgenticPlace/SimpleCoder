# mindx/core/agint.py (Version 2.0 - Hardened Orchestrator)
"""
This module defines AGInt, a high-level orchestrator or "meta-agent".
AGInt operates on a strategic P-O-D-A (Perceive-Orient-Decide-Act) loop.
It assesses the overall situation, decides on a high-level strategy (e.g.,
delegate to a worker agent, research, self-repair), and then executes that
strategy. It does not perform low-level task planning itself; it delegates
that responsibility to subordinate agents like BDIAgent.
"""
from __future__ import annotations
import asyncio
import json
import time
from enum import Enum, auto
from typing import Dict, Any, Optional, Tuple

# Assuming these are actual, well-defined modules
from utils.config import Config
from utils.logging_config import get_logger
from llm.llm_interface import LLMHandlerInterface
from llm.model_registry import ModelRegistry
from llm.model_selector import TaskType
from core.bdi_agent import BDIAgent, AgentStatus as BDIAgentStatus # Import BDI's state enum
# Stubs for other agents/tools
from orchestration.coordinator_agent import CoordinatorAgent, InteractionType, InteractionStatus
from agents.memory_agent import MemoryAgent

logger = get_logger(__name__)

class AGIntStatus(Enum):
    """Defines the explicit lifecycle states of the AGInt orchestrator."""
    INACTIVE = auto()
    RUNNING = auto()
    STOPPING = auto()
    FAILED = auto()

class DecisionType(Enum):
    """Defines the high-level strategic decisions AGInt can make."""
    DELEGATE_TO_BDI = auto()
    RESEARCH_WEB = auto()
    PERFORM_SELF_REPAIR = auto()
    ENTER_COOLDOWN = auto()

class AGInt:
    """The AGInt Orchestrator Agent."""
    def __init__(self,
                 agent_id: str,
                 bdi_agent: BDIAgent,
                 model_registry: ModelRegistry,
                 config: Optional[Config] = None,
                 tools: Optional[Dict[str, Any]] = None,
                 coordinator_agent: Optional[CoordinatorAgent] = None,
                 memory_agent: Optional[MemoryAgent] = None):
        """Initializes the AGInt orchestrator."""
        self.agent_id = agent_id
        self.log_prefix = f"AGInt ({self.agent_id}):"
        self.logger = get_logger(f"agint.{self.agent_id}")
        self.logger.info(f"{self.log_prefix} Initializing...")

        self.bdi_agent = bdi_agent
        self.model_registry = model_registry
        self.config = config or Config()
        self.coordinator_agent = coordinator_agent
        self.memory_agent = memory_agent
        self.tools = tools or {}
        
        self.status = AGIntStatus.INACTIVE
        self.primary_directive: Optional[str] = None
        self.main_loop_task: Optional[asyncio.Task] = None
        
        # This context is crucial: it carries the result of the last action into the next cycle's perception.
        self.last_action_result_context: Optional[Dict[str, Any]] = None
        # This summary is AGInt's own high-level belief about its operational state.
        self.internal_state_summary: Dict[str, Any] = {"llm_operational": True, "awareness": "System starting up."}


    def start(self, directive: str):
        """Starts the main cognitive loop of the agent."""
        if self.status == AGIntStatus.RUNNING:
            self.logger.warning(f"{self.log_prefix} Start called but agent is already running.")
            return
        self.status = AGIntStatus.RUNNING
        self.primary_directive = directive
        self.last_action_result_context = {"success": True, "result": {"message": "Agent startup initiated."}}
        self.main_loop_task = asyncio.create_task(self._cognitive_loop())
        self.logger.info(f"{self.log_prefix} Cognitive loop started with directive: '{directive}'")

    async def stop(self):
        """Stops the main cognitive loop gracefully."""
        if self.status != AGIntStatus.RUNNING: return
        self.status = AGIntStatus.STOPPING
        if self.main_loop_task:
            self.main_loop_task.cancel()
            try: await self.main_loop_task
            except asyncio.CancelledError: pass # Expected on cancellation
        self.status = AGIntStatus.INACTIVE
        self.logger.info(f"{self.log_prefix} Cognitive loop stopped.")

    async def _cognitive_loop(self):
        """The main P-O-D-A (Perceive-Orient-Decide-Act) cycle."""
        while self.status == AGIntStatus.RUNNING:
            try:
                perception_data = self._perceive()
                if self.memory_agent: await self.memory_agent.save_memory(perception_data, 'agint_perception')

                strategic_decision = await self._orient_and_decide(perception_data)
                if self.memory_agent: await self.memory_agent.save_memory(strategic_decision, 'agint_decision')
                
                success, result_data = await self._act(strategic_decision)
                
                self.last_action_result_context = {"success": success, "result": result_data}
                if self.memory_agent: await self.memory_agent.save_memory(self.last_action_result_context, 'agint_action_result')

                await asyncio.sleep(self.config.get("agint.cycle_delay_seconds", 5.0))
            except asyncio.CancelledError:
                self.logger.info(f"{self.log_prefix} Cognitive loop cancelled.")
                break
            except Exception as e:
                self.logger.critical(f"{self.log_prefix} UNHANDLED CRITICAL ERROR in cognitive loop: {e}. Agent FAILED.", exc_info=True)
                self.status = AGIntStatus.FAILED
                break
        self.logger.info(f"{self.log_prefix} Cognitive loop terminated with status {self.status.name}.")

    def _perceive(self) -> Dict[str, Any]:
        """Gathers all relevant information for the current decision-making cycle."""
        self.logger.info("Perceiving current state...")
        perception = {
            "timestamp": time.time(),
            "agint_status": self.status.name,
            "primary_directive": self.primary_directive,
            "last_action_result": self.last_action_result_context,
            "internal_state_summary": self.internal_state_summary,
        }
        if not self.last_action_result_context.get("success"):
             self.logger.warning(f"Perceiving failure from last action: {self.last_action_result_context.get('result')}")
        return perception

    async def _orient_and_decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """Analyzes perceptions to form situational awareness and then makes a strategic decision."""
        # Step 1: Form Situational Awareness
        awareness_prompt = (
            f"You are the orientation module for an AI orchestrator. Your directive is: '{self.primary_directive}'.\n"
            f"Based on the following perception data, synthesize a brief, one-sentence summary of the current situation. Focus on any failures or key outcomes from the last action.\n\n"
            f"Perception Data:\n{json.dumps(perception, default=str, indent=2)}\n\n"
            f"Situational Awareness:"
        )
        situational_awareness = await self._execute_cognitive_task(awareness_prompt, TaskType.REASONING)
        if not situational_awareness:
            situational_awareness = "Cognitive failure: Could not determine situational awareness."
        self.internal_state_summary["awareness"] = situational_awareness
        self.logger.info(f"Situational Awareness: {situational_awareness}")

        # Step 2: Make a Strategic Decision based on rules and awareness
        decision_type = self._decide_rule_based(perception)
        
        decision_prompt = (
            f"You are the decision module for an AI orchestrator. Your directive is: '{self.primary_directive}'.\n"
            f"Current Situation: {situational_awareness}\n"
            f"A rule-based system has chosen the strategic action: '{decision_type.name}'.\n\n"
            f"Your task is to formulate the specific parameters for this action. "
            f"If delegating, what is the clear, actionable sub-task for the BDI agent? "
            f"If researching, what is the precise search query?\n\n"
            f"Respond ONLY with a valid JSON object containing the parameters for the chosen action."
        )
        
        params_str = await self._execute_cognitive_task(decision_prompt, TaskType.PLANNING, json_mode=True)
        try:
            params = json.loads(params_str) if params_str else {}
            return {"type": decision_type, "params": params}
        except json.JSONDecodeError:
            return {"type": DecisionType.ENTER_COOLDOWN, "params": {"reason": "LLM returned invalid JSON for decision parameters."}}
            
    def _decide_rule_based(self, perception: Dict[str, Any]) -> DecisionType:
        """A simple, deterministic decision tree to guide the LLM."""
        if not self.internal_state_summary.get("llm_operational"):
            return DecisionType.PERFORM_SELF_REPAIR
        if not perception["last_action_result"].get("success"):
            return DecisionType.RESEARCH_WEB
        return DecisionType.DELEGATE_TO_BDI

    async def _act(self, decision: Dict[str, Any]) -> Tuple[bool, Any]:
        """Routes the strategic decision to the appropriate execution function."""
        decision_type = decision.get("type")
        params = decision.get("params", {})
        self.logger.info(f"--- AGInt ACTION: Executing '{decision_type.name if decision_type else 'NONE'}' ---")
        
        action_map = {
            DecisionType.DELEGATE_TO_BDI: self._act_delegate_to_bdi,
            DecisionType.RESEARCH_WEB: self._act_research_web,
            DecisionType.PERFORM_SELF_REPAIR: self._act_self_repair,
            DecisionType.ENTER_COOLDOWN: self._act_cooldown,
        }
        action_func = action_map.get(decision_type)
        if not action_func:
            return True, {"message": f"Decision type '{decision_type.name}' is a no-op."}
        
        try:
            return await action_func(params)
        except Exception as e:
            self.logger.error(f"Exception during ACT phase for '{decision_type.name}': {e}", exc_info=True)
            return False, {"error": f"Exception during action execution: {e}"}

    async def _act_delegate_to_bdi(self, params: Dict) -> Tuple[bool, Any]:
        """Delegates a task to the subordinate BDI agent and processes its result."""
        task_description = params.get("task_description") or self.primary_directive
        if not task_description:
            return False, {"error": "No task description available for BDI delegation."}

        self.logger.info(f"Delegating to BDI Agent: '{task_description[:200]}...'")
        try:
            # Ensure the BDI agent is ready for a new task
            if self.bdi_agent.status not in [BDIAgentStatus.INITIALIZED, BDIAgentStatus.IDLE_COMPLETE, BDIAgentStatus.GOAL_ACHIEVED]:
                is_ready = await self.bdi_agent.async_init()
                if not is_ready: return False, {"error": "Subordinate BDI agent failed to initialize."}
                
            self.bdi_agent.set_primary_goal(task_description)
            final_bdi_status = await self.bdi_agent.run()
            
            if final_bdi_status == BDIAgentStatus.GOAL_ACHIEVED:
                self.logger.info("BDI agent successfully achieved its goal.")
                return True, {"message": "Subordinate BDI agent completed its task successfully."}
            else:
                self.logger.warning(f"BDI agent finished with non-success status: {final_bdi_status.name}")
                return False, {"error": "BDI_TASK_FAILED", "final_status": final_bdi_status.name}
        except Exception as e:
            self.logger.error(f"Exception during BDI delegation: {e}", exc_info=True)
            return False, {"error": f"An exception occurred while delegating to BDI agent: {e}"}

    async def _act_research_web(self, params: Dict) -> Tuple[bool, Any]:
        """Executes a web search query using a dedicated tool."""
        web_search_tool = self.tools.get("web_search")
        if not web_search_tool: return False, {"error": "WebSearchTool not available."}

        query = params.get("query")
        if not query: return False, {"error": "No query provided for research."}
        
        self.logger.info(f"Executing research with query: '{query}'")
        result = await web_search_tool.execute(query=query)
        # Assuming the tool returns a dict with a 'status' key
        return result.get("status") == "SUCCESS", result

    async def _act_cooldown(self, params: Dict) -> Tuple[bool, Any]:
        """Pauses the agent for a configured duration."""
        reason = params.get("reason", "No reason provided.")
        cooldown_period = self.config.get("agint.llm_failure_cooldown_seconds", 30)
        self.logger.warning(f"Entering COOLDOWN for {cooldown_period}s. Reason: {reason}")
        await asyncio.sleep(cooldown_period)
        return True, {"message": f"Cooldown complete after {cooldown_period}s."}

    async def _act_self_repair(self, params: Dict) -> Tuple[bool, Any]:
        """Attempts to repair the system, focusing on LLM connectivity."""
        self.logger.info("Initiating self-repair sequence...")
        # In a real system, this might call a CoordinatorAgent, but here we focus on LLM health.
        await self.model_registry.force_reload()
        
        self.logger.info("Verifying LLM connectivity post-repair...")
        verification_result = await self._execute_cognitive_task(
            "Connectivity check. Respond ONLY with the word 'OK'.",
            TaskType.HEALTH_CHECK
        )
        
        if verification_result and "OK" in verification_result:
            self.internal_state_summary["llm_operational"] = True
            self.logger.info("Self-repair successful. LLM connectivity restored.")
            return True, {"message": "Self-repair sequence completed and verified."}
        else:
            self.internal_state_summary["llm_operational"] = False
            self.logger.error("Self-repair FAILED. LLM connectivity could not be restored.")
            return False, {"error": "Self-repair verification failed."}
            
    async def _execute_cognitive_task(self, prompt: str, task_type: TaskType, **kwargs) -> Optional[str]:
        """Selects the best available LLM and executes a cognitive task."""
        try:
            best_model_id = self.model_registry.select_model(task_type)
            if not best_model_id:
                self.logger.error(f"No suitable model found for task type: {task_type.name}")
                self.internal_state_summary["llm_operational"] = False
                return None
                
            handler = self.model_registry.get_handler_for_model(best_model_id)
            response = await handler.generate_text(prompt, model=best_model_id, **kwargs)
            self.internal_state_summary["llm_operational"] = True
            return response
        except Exception as e:
            self.logger.error(f"Cognitive task execution failed: {e}", exc_info=True)
            self.internal_state_summary["llm_operational"] = False
            return None
