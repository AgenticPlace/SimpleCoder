# orchestration/coordinator_agent.py (Version 3.0 - Concurrency & Events)
"""
This module defines the CoordinatorAgent, the central operating system and
service bus for the MindX Sovereign Intelligent Organization (SIO).

Core Philosophy: "Do one thing and do it well."
The Coordinator's role is to manage and route interactions, provide core system
services, and enable decoupled communication. It is a "headless" kernel that does
not perform strategic reasoning.

Improvements in v3.0:
- Concurrency Management: Implemented an asyncio.Semaphore to limit concurrent
  execution of resource-intensive tasks (e.g., component improvement),
  ensuring system stability under load.
- Event-Driven Pub/Sub Bus: Added `subscribe` and `publish_event` methods to
  allow for a decoupled, event-driven architecture where agents can react to
  system-wide events without direct coupling.
- Role Purity: Continues the focus on being a pure orchestrator, with health
  and resource monitoring delegated to specialized agents.
"""
from __future__ import annotations
import asyncio
import json
import time
import uuid
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional, Callable, Coroutine

# Assuming these are actual, well-defined modules
from utils.config import Config, PROJECT_ROOT
from utils.logging_config import get_logger
# Monitoring agents will be registered but their logic is external.
# from monitoring.resource_monitor import ResourceMonitor 
# from monitoring.performance_monitor import PerformanceMonitor

logger = get_logger(__name__)

# --- Core Data Structures ---

class InteractionType(Enum):
    QUERY = "query"
    SYSTEM_ANALYSIS = "system_analysis"
    COMPONENT_IMPROVEMENT = "component_improvement"
    AGENT_REGISTRATION = "agent_registration"
    PUBLISH_EVENT = "publish_event" # New interaction type for the event bus

class InteractionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROUTED_TO_TOOL = "routed_to_tool"

class Interaction:
    """A data object representing a single, trackable request within the system."""
    def __init__(self, interaction_id: str, interaction_type: InteractionType, content: str, **kwargs):
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

# --- The Coordinator Agent Kernel ---

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
                await cls._instance.async_init() # Ensure async components are ready
            return cls._instance

    def __init__(self,
                 config_override: Optional[Config] = None,
                 test_mode: bool = False,
                 **kwargs):
        """Initializes the CoordinatorAgent."""
        if hasattr(self, '_initialized') and self._initialized and not test_mode:
            return

        self.config = config_override or Config(test_mode=test_mode)
        
        # --- System Registries and Services ---
        self.agent_registry: Dict[str, Any] = {}
        self.tool_registry: Dict[str, Any] = {}

        # --- Interaction Management ---
        self.interactions: Dict[str, Interaction] = {}
        self.interaction_handlers: Dict[InteractionType, Callable] = self._get_interaction_handlers()

        # --- IMPROVEMENT: Concurrency Management ---
        max_heavy_tasks = self.config.get("coordinator.max_concurrent_heavy_tasks", 2)
        self.heavy_task_semaphore = asyncio.Semaphore(max_heavy_tasks)
        self.logger = get_logger(f"coordinator_agent")
        self.logger.info(f"Heavy task concurrency limit set to: {max_heavy_tasks}")

        # --- IMPROVEMENT: Event-Driven Pub/Sub Bus ---
        self.event_listeners: Dict[str, List[Callable]] = defaultdict(list)

        self._initialized = True
        self.logger.info("CoordinatorAgent initialized. Awaiting async setup.")

    async def async_init(self):
        """Asynchronously initializes monitoring components and registers self."""
        # The Coordinator is now "headless" and doesn't need its own LLM.
        # Resource/Performance monitors are external agents that will register themselves.
        self.register_agent(
            agent_id="coordinator_agent", agent_type="kernel",
            description="MindX Central Kernel and Service Bus",
            instance=self
        )
        await self._initialize_tools()
        self.logger.info("CoordinatorAgent fully initialized.")

    def _get_interaction_handlers(self) -> Dict[InteractionType, Callable]:
        """Maps interaction types to their handler methods."""
        return {
            InteractionType.SYSTEM_ANALYSIS: self._handle_system_analysis,
            InteractionType.COMPONENT_IMPROVEMENT: self._handle_component_improvement,
            InteractionType.PUBLISH_EVENT: self._handle_publish_event,
            # AGENT_REGISTRATION is handled by the public `register_agent` method
        }

    async def _initialize_tools(self):
        """Initializes the tools the Coordinator itself needs to function."""
        try:
            from tools.self_improvement_tool import SelfImprovementTool
            sia_tool = SelfImprovementTool(config=self.config)
            self.tool_registry["self_improvement_tool"] = sia_tool
            self.logger.info("SelfImprovementTool successfully loaded by Coordinator.")
        except ImportError:
            self.logger.error("CRITICAL: SelfImprovementTool not found. The Coordinator cannot perform code modifications.")

    # --- Public API for Agent Society ---

    def register_agent(self, agent_id: str, agent_type: str, description: str, instance: Any):
        """Registers a running agent instance, making it known to the system."""
        self.agent_registry[agent_id] = {
            "agent_id": agent_id, "agent_type": agent_type,
            "description": description, "instance": instance,
            "status": "active", "registered_at": time.time(),
        }
        self.logger.info(f"Registered agent '{agent_id}' (Type: {agent_type}). Total agents: {len(self.agent_registry)}")

    def subscribe(self, topic: str, callback: Callable[..., Coroutine[Any, Any, None]]):
        """Allows an agent to listen for a specific event topic."""
        self.event_listeners[topic].append(callback)
        self.logger.info(f"New subscription to topic '{topic}' by '{getattr(callback, '__qualname__', 'unnamed_callback')}'")

    async def publish_event(self, topic: str, data: Dict[str, Any]):
        """Publishes an event, triggering all subscribed callbacks concurrently."""
        self.logger.info(f"Publishing event on topic '{topic}' with data keys: {list(data.keys())}")
        if topic in self.event_listeners:
            tasks = [callback(data) for callback in self.event_listeners[topic]]
            # Gather and log exceptions without stopping other listeners
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    callback_name = getattr(self.event_listeners[topic][i], '__qualname__', 'unnamed_callback')
                    self.logger.error(f"Error in event listener '{callback_name}' for topic '{topic}': {result}", exc_info=result)

    async def create_and_process_interaction(self, interaction_type: InteractionType, content: str, **kwargs) -> Interaction:
        """A convenience method to create and immediately process an interaction."""
        interaction = Interaction(
            interaction_id=f"inter_{interaction_type.name.lower()}_{uuid.uuid4().hex[:8]}",
            interaction_type=interaction_type,
            content=content,
            **kwargs
        )
        self.interactions[interaction.interaction_id] = interaction
        self.logger.info(f"Created interaction '{interaction.interaction_id}' of type '{interaction.interaction_type.name}'.")
        return await self.process_interaction(interaction)

    async def process_interaction(self, interaction: Interaction) -> Interaction:
        """The main entry point for processing an interaction."""
        if interaction.status != InteractionStatus.PENDING:
            self.logger.warning(f"Attempted to process non-PENDING interaction '{interaction.interaction_id}'.")
            return interaction

        self.logger.info(f"Processing interaction '{interaction.interaction_id}' (Type: {interaction.interaction_type.name})")
        interaction.status = InteractionStatus.IN_PROGRESS
        
        handler = self.interaction_handlers.get(interaction.interaction_type)
        if not handler:
            interaction.status = InteractionStatus.FAILED
            interaction.error = f"No handler for interaction type '{interaction.interaction_type.name}'."
        else:
            try:
                await handler(interaction)
            except Exception as e:
                self.logger.error(f"Unhandled exception in handler for '{interaction.interaction_id}': {e}", exc_info=True)
                interaction.status = InteractionStatus.FAILED
                interaction.error = f"Unhandled handler exception: {str(e)}"

        interaction.completed_at = time.time()
        self.logger.info(f"Finished processing '{interaction.interaction_id}'. Final status: {interaction.status.name}")
        return interaction

    # --- Interaction Handler Implementations ---

    async def _handle_system_analysis(self, interaction: Interaction):
        """Gathers raw telemetry about the system state. Does not perform analysis."""
        self.logger.debug(f"Handling SYSTEM_ANALYSIS for '{interaction.interaction_id}'.")
        # In a real system, it would query registered monitoring agents.
        # For now, we simulate this by providing basic kernel info.
        telemetry_data = {
            "registered_agents_count": len(self.agent_registry),
            "active_interaction_count": len([i for i in self.interactions.values() if i.status == InteractionStatus.IN_PROGRESS]),
            "event_bus_topics": list(self.event_listeners.keys()),
        }
        interaction.response = {"status": "SUCCESS", "telemetry": telemetry_data}
        interaction.status = InteractionStatus.COMPLETED

    async def _handle_component_improvement(self, interaction: Interaction):
        """

        Handles a request to improve a component by dispatching it to the
        SIA tool, respecting the concurrency limit.
        """
        self.logger.debug(f"Handling COMPONENT_IMPROVEMENT for '{interaction.interaction_id}'.")
        sia_tool = self.tool_registry.get("self_improvement_tool")
        if not sia_tool:
            interaction.status = InteractionStatus.FAILED
            interaction.error = "SelfImprovementTool is not available."
            return

        interaction.status = InteractionStatus.ROUTED_TO_TOOL
        self.logger.info(f"Acquiring semaphore for heavy task: {interaction.interaction_id}")
        async with self.heavy_task_semaphore:
            self.logger.info(f"Semaphore acquired. Processing heavy task: {interaction.interaction_id}")
            
            tool_params = interaction.metadata
            sia_result = await sia_tool.execute(**tool_params)
            
            interaction.response = sia_result
            if sia_result.get("status") == "SUCCESS":
                interaction.status = InteractionStatus.COMPLETED
                await self.publish_event(
                    "component.improvement.success",
                    {"interaction_id": interaction.interaction_id, "metadata": interaction.metadata}
                )
            else:
                interaction.status = InteractionStatus.FAILED
                interaction.error = sia_result.get("message", "SIA tool reported a failure.")
                await self.publish_event(
                    "component.improvement.failure",
                    {"interaction_id": interaction.interaction_id, "error": interaction.error, "metadata": interaction.metadata}
                )
        self.logger.info(f"Semaphore released for heavy task: {interaction.interaction_id}")

    async def _handle_publish_event(self, interaction: Interaction):
        """Handles a request from an agent to publish an event to the bus."""
        topic = interaction.metadata.get("topic")
        data = interaction.metadata.get("data")
        if not isinstance(topic, str) or not isinstance(data, dict):
            interaction.status = InteractionStatus.FAILED
            interaction.error = "PUBLISH_EVENT requires 'topic' (str) and 'data' (dict) in metadata."
            return

        await self.publish_event(topic, data)
        interaction.response = {"status": "SUCCESS", "message": f"Event published to topic '{topic}'."}
        interaction.status = InteractionStatus.COMPLETED

    async def shutdown(self):
        """Gracefully shuts down the Coordinator."""
        self.logger.info(f"CoordinatorAgent shutting down...")
        # Add shutdown logic for any running tasks or persistent connections here
        self.logger.info(f"CoordinatorAgent shutdown complete.")

# --- Factory Function ---

async def get_coordinator_agent_mindx_async(config_override: Optional[Config] = None, test_mode: bool = False) -> CoordinatorAgent:
    """The preferred, safe factory for creating or retrieving the Coordinator instance."""
    instance = await CoordinatorAgent.get_instance(config_override=config_override, test_mode=test_mode)
    return instance
