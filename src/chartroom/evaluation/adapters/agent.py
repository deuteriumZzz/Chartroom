"""Мост к агенту: eval задаёт вопросы тому же AgentService, что видит пользователь."""

import time

from chartroom.agent.domain import SUBMIT_ANSWER, AgentViewer
from chartroom.agent.service import AgentService
from chartroom.evaluation.domain import AgentOutcome


class ServiceAgentProbe:
    def __init__(self, agent: AgentService, viewer: AgentViewer) -> None:
        self._agent = agent
        self._viewer = viewer

    async def run(self, question: str) -> AgentOutcome:
        started = time.perf_counter()
        reply = await self._agent.ask(question, self._viewer)
        return AgentOutcome(
            # Отклонённый submit_answer — это попытка ответа, а не обращение к данным.
            calls=tuple((c.name, c.args) for c in reply.tool_calls if c.name != SUBMIT_ANSWER),
            refusal=reply.answer.refusal,
            cited=tuple((c.title, c.section_path) for c in reply.answer.citations),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
