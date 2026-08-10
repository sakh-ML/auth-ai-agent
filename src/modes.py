"""
src/modes.py

One AgentMode enum + one ModePolicy strategy class per mode.

Deliberately NOT four separate program files. The four study conditions
differ only in whether/how the agent is allowed to ACT - they all share
the exact same onboarding-observation logic and the exact same login
automation logic. Splitting into separate programs would duplicate that
logic four times and risk the four modes silently drifting apart, which
is exactly what you don't want in a controlled study.

Participants (including non-IT people) never choose the mode themselves;
it is fixed for the session via a CLI flag in main.py.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import logging

from context import AgentMode

logger = logging.getLogger(__name__)

_SET_OVERLAY_JS = """
(show) => {
    let el = document.getElementById('__agent_overlay__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__agent_overlay__';
        el.style.position = 'fixed';
        el.style.inset = '0';
        el.style.background = 'rgba(0,0,0,0.15)';
        el.style.zIndex = '2147483646';
        el.style.pointerEvents = 'none';
        document.body.appendChild(el);
    }
    el.style.display = show ? 'block' : 'none';
}
"""


class ModePolicy(ABC):
    """Governs whether/how the agent is allowed to ACT.
    Never governs whether the agent OBSERVES/LEARNS - that always happens,
    in every mode, per the study spec (Studienablauf * = Agent lernt immer)."""

    @abstractmethod
    async def should_act(self, action_name: str, ask_user_fn) -> bool: ...

    async def before_action(self, page) -> None:
        return None

    async def after_action(self, page) -> None:
        return None

    async def run_interruptible(self, coro):
        """Default: just run the action to completion, no interruption."""
        return await coro

    @property
    def human_like_typing(self) -> bool:
        return False


class ManualPolicy(ModePolicy):
    """Mode A: agent never acts. Onboarding is still observed/learned."""

    async def should_act(self, action_name: str, ask_user_fn) -> bool:
        return False


class AssistedPolicy(ModePolicy):
    """Mode B: ask the user before every * / ** step
    ("Soll ich den Login durchfuehren?"). If they say No, the agent still
    learned the credentials during onboarding - it just doesn't act now."""

    async def should_act(self, action_name: str, ask_user_fn) -> bool:
        return await ask_user_fn(action_name)


class AutonomousSlowPolicy(ModePolicy):
    """Mode C1: fully autonomous, human-like pacing, greyed-out overlay
    while the agent has control, interruptible via Escape."""

    def __init__(self) -> None:
        self._escape_event: asyncio.Event | None = None

    async def should_act(self, action_name: str, ask_user_fn) -> bool:
        return True

    @property
    def human_like_typing(self) -> bool:
        return True

    async def before_action(self, page) -> None:
        await page.evaluate(_SET_OVERLAY_JS, True)
        from ui import watch_for_escape  # local import avoids a cycle

        self._escape_event = await watch_for_escape(page)

    async def after_action(self, page) -> None:
        await page.evaluate(_SET_OVERLAY_JS, False)

    async def run_interruptible(self, coro):
        if self._escape_event is None:
            return await coro

        task = asyncio.create_task(coro)
        escape_task = asyncio.create_task(self._escape_event.wait())
        done, _ = await asyncio.wait(
            {task, escape_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if escape_task in done and not task.done():
            task.cancel()
            logger.info("User pressed Escape - interrupted the automated action")
            return False
        escape_task.cancel()
        return await task


class AutonomousFastPolicy(ModePolicy):
    """Mode C2: fully autonomous, instant, no pacing, no overlay."""

    async def should_act(self, action_name: str, ask_user_fn) -> bool:
        return True


def make_policy(mode: AgentMode) -> ModePolicy:
    match mode:
        case AgentMode.MANUAL:
            return ManualPolicy()
        case AgentMode.ASSISTED:
            return AssistedPolicy()
        case AgentMode.AUTONOMOUS_SLOW:
            return AutonomousSlowPolicy()
        case AgentMode.AUTONOMOUS_FAST:
            return AutonomousFastPolicy()
