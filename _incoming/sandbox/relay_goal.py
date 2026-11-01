"""Relay goal pin. Same Hermes goal store Desktop uses. Not a second goal file."""
import sys
import time
from pathlib import Path

HERMES = Path(r"C:\Users\eMitchell109\AppData\Local\hermes\hermes-agent")
if str(HERMES) not in sys.path:
    sys.path.insert(0, str(HERMES))

from hermes_cli.goals import GoalManager

SESSION_ID = "relay-eddie-echo"
MAX_TEXT = 500


def snapshot():
    state = GoalManager(SESSION_ID).state
    if state is None or state.status not in {"active", "paused"}:
        return {"session_id": SESSION_ID, "status": "none", "goal": ""}
    return {
        "session_id": SESSION_ID,
        "status": state.status,
        "goal": state.goal,
        "turns_used": state.turns_used,
        "max_turns": state.max_turns,
        "last_verdict": state.last_verdict or "",
        "waiting": bool(state.waiting_on_session or state.waiting_on_pid or state.waiting_on_delegations or (state.waiting_until and state.waiting_until > time.time())),
    }


def apply(action, text=""):
    if action == "status":
        return snapshot()
    manager = GoalManager(SESSION_ID)
    if action == "clear":
        manager.clear()
        return snapshot()
    if action == "set":
        goal = text.strip() if isinstance(text, str) else ""
        if not goal or len(goal) > MAX_TEXT:
            raise ValueError("Use 1 to 500 characters.")
        manager.set(goal)
        saved = snapshot()
        if saved.get("goal") != goal or saved.get("status") != "active":
            raise RuntimeError("Hermes did not keep the goal.")
        return saved
    if action == "pause":
        if manager.pause("user-paused") is None:
            raise ValueError("No goal to pause.")
        return snapshot()
    if action == "resume":
        if manager.resume() is None:
            raise ValueError("No goal to resume.")
        return snapshot()
    raise ValueError("Use set, clear, pause, or resume.")
