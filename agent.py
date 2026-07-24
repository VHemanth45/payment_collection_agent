"""Public conversation contract for the payment collection agent.

The account lookup and validation flow is intentionally added in a later
ticket. This module establishes the stable, turn-based interface that those
flows will build on.
"""

from __future__ import annotations

from enum import Enum, auto


class _ConversationState(Enum):
    """Internal state names; these must never be shown to callers."""

    NEED_ACCOUNT = auto()


class Agent:
    """Process one user turn at a time for a payment conversation."""

    _ACCOUNT_PROMPT = "Please provide your account ID to get started."
    _ACCOUNT_RETRY_PROMPT = (
        "I still need your account ID to continue. "
        "Please provide it, for example, ACC1001."
    )

    def __init__(self) -> None:
        self._state = _ConversationState.NEED_ACCOUNT

    def next(self, user_input: str) -> dict[str, str]:
        """Process one user turn and return a deterministic message.

        Account extraction and lookup are introduced by task 02. Until then,
        the shell keeps requesting the first required piece of information.
        Non-string values are treated as unusable input so the public method
        still honours its response contract at runtime.
        """

        if self._state is _ConversationState.NEED_ACCOUNT:
            if isinstance(user_input, str) and user_input.strip():
                return {"message": self._ACCOUNT_RETRY_PROMPT}
            return {"message": self._ACCOUNT_PROMPT}

        # Keep a defensive fallback so future state additions cannot violate
        # the response contract if a state is introduced without a message.
        return {"message": self._ACCOUNT_PROMPT}
