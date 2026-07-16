"""Chainlit app: interactive modelling of positive AI-2035 scenarios.

Flow:
1. Login (password auth — required by the persistent data layer).
2. Guided intake: the user provides Background (#2) and Assumptions (#3).
   Goal (#1) and Work assignment (#4) come from the configurable system prompt.
3. The assembled first turn is sent to the configured LLM and streamed back.
4. Free multi-turn conversation for iterative refinement.
"""

from __future__ import annotations

from datetime import date

import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

import config
from llm import stream_chat

config.validate()


def _system_prompt() -> str:
    """System prompt with today's date appended, so the model anchors the story
    in the present (not its training-time assumptions) and moves forward to 2035."""
    return (
        f"{config.SYSTEM_PROMPT}\n\n"
        f"The current date is {date.today().isoformat()}. Treat this as \"now\": "
        f"open the scenario in the present and move forward toward 2035. "
        f"Never set the opening in a year earlier than the current date."
    )

HISTORY_KEY = "history"


# --- Persistence (Heroku Postgres) ------------------------------------------

if config.DATABASE_URL:

    @cl.data_layer
    def get_data_layer():
        return SQLAlchemyDataLayer(
            conninfo=config.DATABASE_URL,
            ssl_require=config.DATABASE_SSL,
        )


# --- Auth -------------------------------------------------------------------


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """Single shared credential for the facilitated test session."""
    if (
        config.APP_PASSWORD
        and username == config.APP_USERNAME
        and password == config.APP_PASSWORD
    ):
        return cl.User(identifier=username, metadata={"role": "user"})
    return None


# --- Intake -----------------------------------------------------------------

INTAKE_BACKGROUND = (
    "**Question 1 of 2**\n\n"
    "Before you give me your set of alternative, non-mainstream assumptions "
    "about the state and trajectory of AI and society, please provide me with "
    "some context in which you place these assumptions. This can be a specific "
    "aspect of the current situation to focus on, and/or your assessment of it.\n\n"
    "_Example: 'Consider that AI development is mainly driven by a few highly "
    "valuated start-ups in few regions of the world, driven by massive amounts "
    "of venture capital and the promise of developing AGI that is in immediate "
    "reach. They invest heavily in compute infrastructure that will be outdated "
    "in about 5 years after purchase.'_"
)

INTAKE_ASSUMPTIONS = (
    "**Question 2 of 2**\n\n"
    "Now state your assumptions that deviate from the mainstream assumptions "
    "undergirding popular, often negative scenarios.\n\n"
    "_Example: 'There will be no fundamental leaps towards AGI in the next "
    "10 years.'_"
)


STAGE_KEY = "stage"
BACKGROUND_KEY = "background"


async def _send(content: str) -> None:
    """Send a top-level assistant message. Setting parent_id=None makes it a
    root step (not a child of the framework's per-handler "run" step, which is
    not persisted) so it renders correctly when a thread is resumed."""
    msg = cl.Message(content=content)
    msg.parent_id = None
    await msg.send()


def _assemble_first_message(background: str, assumptions: str) -> str:
    """Combine components #2 and #3 into the opening user turn."""
    return (
        f"## Context\n\n{background}\n\n"
        f"## Assumptions (deviating from the mainstream)\n\n{assumptions}"
    )


# --- Chat lifecycle ---------------------------------------------------------
#
# The intake (background, then assumptions) is collected as ordinary user
# messages via a small stage machine in on_message — not via AskUserMessage.
# Messages sent by the user are persisted as top-level steps by the framework,
# so both the questions and answers survive a resume.


@cl.on_chat_start
async def on_chat_start():
    await _send(
        "Welcome! This interface helps you explore a **positive future "
        "scenario for our society with AI in ten years**.\n\n"
        "I will first ask you two short questions to initiate the exploration. "
        "After that, you can continue the conversation freely and refine the "
        "scenario iteratively (e.g., by challenging my extrapolations, adding "
        "new or changing old assumptions, pruning 'branches', etc.)."
    )
    await _send(INTAKE_BACKGROUND)
    cl.user_session.set(STAGE_KEY, "background")
    cl.user_session.set(HISTORY_KEY, [])


@cl.on_chat_resume
async def on_chat_resume(thread):
    """Reopen a past conversation: rebuild the in-memory history from the
    persisted steps so the model keeps full context. Chainlit renders the
    stored messages in the UI automatically."""
    history: list[dict] = []
    for step in thread.get("steps", []) or []:
        content = (step.get("output") or "").strip()
        if not content:
            continue
        step_type = step.get("type")
        if step_type == "user_message":
            history.append({"role": "user", "content": content})
        elif step_type == "assistant_message":
            history.append({"role": "assistant", "content": content})
    cl.user_session.set(HISTORY_KEY, history)
    cl.user_session.set(STAGE_KEY, "chatting")


@cl.on_message
async def on_message(message: cl.Message):
    stage = cl.user_session.get(STAGE_KEY) or "chatting"

    # Intake 1/2: capture background, then ask for assumptions.
    if stage == "background":
        cl.user_session.set(BACKGROUND_KEY, message.content)
        cl.user_session.set(STAGE_KEY, "assumptions")
        await _send(INTAKE_ASSUMPTIONS)
        return

    # Intake 2/2: capture assumptions, assemble the opening turn, respond.
    if stage == "assumptions":
        background = cl.user_session.get(BACKGROUND_KEY) or ""
        first_message = _assemble_first_message(background, message.content)
        history = [{"role": "user", "content": first_message}]
        cl.user_session.set(HISTORY_KEY, history)
        cl.user_session.set(STAGE_KEY, "chatting")
        await _stream_answer(history)
        return

    # Free conversation (multi-turn).
    history: list[dict] = cl.user_session.get(HISTORY_KEY) or []
    history.append({"role": "user", "content": message.content})
    await _stream_answer(history)


async def _stream_answer(history: list[dict]):
    """Stream the model response as a top-level message, then record it."""
    answer = cl.Message(content="")
    answer.parent_id = None  # persist as a root step for correct resume
    await answer.send()

    collected: list[str] = []
    try:
        async for token in stream_chat(_system_prompt(), history):
            collected.append(token)
            await answer.stream_token(token)
    except Exception as exc:  # surface provider/config errors to the tester
        await answer.stream_token(
            f"\n\n_An error occurred: {exc}_"
        )
        await answer.update()
        return

    await answer.update()
    history.append({"role": "assistant", "content": "".join(collected)})
    cl.user_session.set(HISTORY_KEY, history)
