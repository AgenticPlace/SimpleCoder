# orchestration/coordinator_agent.py (Version 2.0 - Hardened Kernel)
"""
This module defines the CoordinatorAgent, the central operating system and
service bus for the MindX Sovereign Intelligent Organization (SIO).

Core Philosophy: "Do one thing and do it well."
The Coordinator's one thing is to manage and route interactions between agents
and provide core system services. It is a "headless" kernel that does not
perform high-level strategic reasoning. It validates requests, dispatches them
to the appropriate handlers or tools, and provides raw telemetry. The cognitive
load of interpreting data and making strategic decisions belongs to higher-level
agents like MastermindAgent.
"""
from __future__ import annotations
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Coroutine

# Assuming these are actual, well-defined modules
from utils.config import Config, PROJECT_ROOT
from utils.logging_config import get_logger
from core.belief_system import BeliefSystem, BeliefSource
from monitoring.resource_monitor import get_resource_monitor_async, ResourceMonitor
from monitoring.performance_monitor import get_performance_monitor_async, PerformanceMonitor

logger = get_logger(__name__)

class InteractionType(Enum):
    QUERY = "query"
    SYSTEM_ANALYSIS = "system_analysis"
    COMPONENT_IMPROVEMENT = "component_improvement"
    # Other types can be added for more specific routing
    AGENT_REGISTRATION = "agent_registration"

class InteractionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROUTED_TO_TOOL = "routed_to_tool"

class Interaction:
    """A data object representing a single, trackable request within the system."""
    # ... (Implementation from previous version is perfect, no changes needed) ...
    def __init__( self, interaction_id: str, interaction_type: InteractionType, content: str, **kwargs):
        self.interaction_id = interaction_id
        self.interaction_type = interaction_type
        self.content = content
        self.metadata = kwargs.get("metadata", {})
        self.status = InteractionStatus.PENDING
        self.response: Optional[Any] = None
        self.error: Optional[str] = None
        self.created_at: float = time.time()
        self.completed_at: Optional[float] = None
    
    def to_dict(self): return self.__dict__

class CoordinatorAgent:
    """
    The central kernel and service bus of the MindX system. It manages agent
    registration, system monitoring, and routes all formal interactions.
    """
    _instance: Optional['CoordinatorAgent'] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls, **kwargs) -> 'CoordinatorAgent':
        """Singleton factory to get or create the Coordinator instance."""
        async with cls._lock:
            if cls._instance is None or kwargs.get("test_mode", False):
                cls._instance = cls(**kwargs)
            return cls._instance

    def __init__(self,
                 belief_system: Optional[BeliefSystem] = None,
                 config_override: Optional[Config] = None,
                 test_mode: bool = False,
                 **kwargs):
        """Initializes the CoordinatorAgent."""
        if hasattr(self, '_initialized') and self._initialized and not test_mode:
            return

        self.config = config_override or Config(test_mode=test_mode)
        self.belief_system = belief_system or BeliefSystem(test_mode=test_mode)
        
        # --- System Services & Registries ---
        self.resource_monitor: Optional[ResourceMonitor] = None
        self.performance_monitor: Optional[PerformanceMonitor] = None
        self.agent_registry: Dict[str, Any] = {}
        self.tool_registry: Dict[str, Any] = {} # For tools the Coordinator uses, like SIA

        # --- Interaction Management ---
        self.interactions: Dict[str, Interaction] = {}
        self.interaction_handlers: Dict[InteractionType, Callable] = self._get_interaction_handlers()

        self.logger = get_logger(f"coordinator_agent")
        self.logger.info("CoordinatorAgent initialized synchronously. Awaiting async_init.")
        self._initialized = True

    async def async_init(self):
        """Asynchronously initializes monitoring components and registers self."""
        self.resource_monitor = await get_resource_monitor_async(self.config)
        self.performance_monitor = await get_performance_monitor_async(self.config)
        self.register_agent(
            agent_id="coordinator_agent", agent_type="kernel",
            description="MindX Central Kernel and Service Bus",
            instance=self
        )
        # The Coordinator needs its own tools, like the one to run the SIA
        await self._initialize_tools()
        self.logger.info("CoordinatorAgent fully initialized with monitoring and tools.")

    def _get_interaction_handlers(self) -> Dict[InteractionType, Callable]:
        """Maps interaction types to their handler methods."""
        return {
            InteractionType.SYSTEM_ANALYSIS: self._handle_system_analysis,
            InteractionType.COMPONENT_IMPROVEMENT: self._handle_component_improvement,
            # QUERY could be handled by dispatching to a specific "QueryAgent"
        }

    async def _initialize_tools(self):
        """
        Initializes the tools that the Coordinator itself needs to function.
        Primarily, this includes the tool responsible for running the SIA script.
        """
        # In a real system, this would load from a config file.
        # For now, we assume a SelfImprovementTool exists.
        try:
            from tools.self_improvement_tool import SelfImprovementTool
            sia_tool = SelfImprovementTool(config=self.config)
            self.tool_registry["self_improvement_tool"] = sia_tool
            self.logger.info("SelfImprovementTool successfully loaded by Coordinator.")
        except ImportError:
            self.logger.error("CRITICAL: SelfImprovementTool not found. The Coordinator cannot perform code modifications.")

    def register_agent(self, agent_id: str, agent_type: str, description: str, instance: Any):
        """Registers a running agent instance with the Coordinator."""
        self.agent_registry[agent_id] = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "description": description,
            "instance": instance,
            "status": "active",
            "registered_at": time.time(),
        }
        self.logger.info(f"Registered agent '{agent_id}' (Type: {agent_type}).")

    async def create_interaction(self, interaction_type: InteractionType, content: str, **kwargs) -> Interaction:
        """Creates and tracks a new interaction object."""
        interaction_id = f"inter_{interaction_type.name.lower()}_{uuid.uuid4().hex[:8]}"
        interaction = Interaction(interaction_id, interaction_type, content, **kwargs)
        self.interactions[interaction_id] = interaction
        self.logger.info(f"Created interaction '{interaction_id}' of type '{interaction_type.name}'.")
        return interaction

    async def process_interaction(self, interaction: Interaction) -> Interaction:
        """
        The main entry point for processing an interaction.
        It validates the interaction and routes it to the correct handler.
        """
        if interaction.status != InteractionStatus.PENDING:
            self.logger.warning(f"Attempted to process interaction '{interaction.interaction_id}' which is not PENDING (Status: {interaction.status.name}).")
            return interaction

        self.logger.info(f"Processing interaction '{interaction.interaction_id}' (Type: {interaction.interaction_type.name})")
        interaction.status = InteractionStatus.IN_PROGRESS
        
        handler = self.interaction_handlers.get(interaction.interaction_type)
        if not handler:
            interaction.status = InteractionStatus.FAILED
            interaction.error = f"No handler registered for interaction type '{interaction.interaction_type.name}'."
            self.logger.error(interaction.error)
        else:
            try:
                # The handler function is responsible for setting the final status, response, and error.
                await handler(interaction)
            except Exception as e:
                self.logger.error(f"Unhandled exception in handler for interaction '{interaction.interaction_id}': {e}", exc_info=True)
                interaction.status = InteractionStatus.FAILED
                interaction.error = f"Unhandled handler exception: {str(e)}"

        interaction.completed_at = time.time()
        self.logger.info(f"Finished processing interaction '{interaction.interaction_id}'. Final status: {interaction.status.name}")
        return interaction

    # --- Interaction Handler Implementations ---

    async def _handle_system_analysis(self, interaction: Interaction):
        """
        Gathers raw telemetry about the system state. Does not perform analysis.
        The cognitive load of interpreting this data is on the requesting agent.
        """
        self.logger.debug(f"Handling SYSTEM_ANALYSIS for interaction '{interaction.interaction_id}'.")
        resource_usage = self.resource_monitor.get_resource_usage() if self.resource_monitor else {}
        perf_metrics = self.performance_monitor.get_summary_metrics() if self.performance_monitor else {}
        
        telemetry_data = {
            "resource_usage": resource_usage,
            "performance_metrics": perf_metrics,
            "registered_agents": list(self.agent_registry.keys()),
            "active_interaction_count": len([i for i in self.interactions.values() if i.status == InteractionStatus.IN_PROGRESS]),
        }
        
        interaction.response = {"status": "SUCCESS", "telemetry": telemetry_data}
        interaction.status = InteractionStatus.COMPLETED

    async def _handle_component_improvement(self, interaction: Interaction):
        """
        Handles a request to improve a software component by dispatching
        it to the specialized SelfImprovementTool.
        """
        self.logger.debug(f"Handling COMPONENT_IMPROVEMENT for interaction '{interaction.interaction_id}'.")
        sia_tool = self.tool_registry.get("self_improvement_tool")
        if not sia_tool:
            interaction.status = InteractionStatus.FAILED
            interaction.error = "SelfImprovementTool is not available to the Coordinator."
            self.logger.error(interaction.error)
            return

        interaction.status = InteractionStatus.ROUTED_TO_TOOL
        
        # The interaction's metadata is expected to contain all necessary parameters for the tool.
        # This decouples the Coordinator from knowing the tool's specific arguments.
        tool_params = interaction.metadata
        
        # The tool's execute method is expected to be robust and return a structured dict.
        sia_result = await sia_tool.execute(**tool_params)
        
        interaction.response = sia_result
        if sia_result.get("status") == "SUCCESS":
            interaction.status = InteractionStatus.COMPLETED
        else:
            interaction.status = InteractionStatus.FAILED
            interaction.error = sia_result.get("message", "SIA tool reported a failure.")

    async def shutdown(self):
        """Gracefully shuts down the Coordinator and its monitoring services."""
        self.logger.info(f"CoordinatorAgent shutting down...")
        if self.resource_monitor:
            self.resource_monitor.stop_monitoring()
        if self.performance_monitor and hasattr(self.performance_monitor, 'shutdown'):
            await self.performance_monitor.shutdown()
        self.logger.info(f"CoordinatorAgent shutdown complete.")

# --- Factory Function ---

async def get_coordinator_agent_mindx_async(config_override: Optional[Config] = None, test_mode: bool = False) -> CoordinatorAgent:
    """The preferred, safe factory for creating or retrieving the Coordinator instance."""
    instance = await CoordinatorAgent.get_instance(
        config_override=config_override,
        test_mode=test_mode
    )
    # Ensure async components are initialized if it's a new instance
    if not hasattr(instance, '_initialized_async_components'):
        await instance.async_init()
        instance._initialized_async_components = True
    return instance
