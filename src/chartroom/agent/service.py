import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from chartroom.agent.domain import (
    DATA_TOOL_SPECS,
    DEFAULT_SEARCH_TOP_K,
    MAX_REQUEST_SECONDS,
    MAX_SEARCH_QUERY,
    MAX_STEPS,
    NO_DATA_TEXT,
    SUBMIT_ANSWER,
    AgentAnswer,
    AgentReply,
    AgentRun,
    AgentViewer,
    InvalidSubmissionError,
    Source,
    ToolCall,
    ToolCallRecord,
    ToolResult,
    finalize,
    normalize_question,
)
from chartroom.agent.ports import (
    AgentModel,
    AgentUnitOfWork,
    DocumentsReader,
    ProcedureSearch,
    ReportsReader,
)
from chartroom.shared.errors import DomainError, ServiceUnavailableError
from chartroom.shared.language import detect_language
from chartroom.shared.schema import validate


class AgentService:
    """Цикл агента: ход модели → вызовы инструментов с правами пользователя → результаты → …"""

    def __init__(
        self,
        model: AgentModel,
        search: ProcedureSearch,
        reports: ReportsReader,
        documents: DocumentsReader,
        uow_factory: Callable[[], AgentUnitOfWork],
    ) -> None:
        self._model = model
        self._search = search
        self._reports = reports
        self._documents = documents
        self._uow_factory = uow_factory

    async def ask(self, question: str, viewer: AgentViewer) -> AgentReply:
        started = time.perf_counter()
        question = normalize_question(question)
        language = detect_language(question)
        conversation = self._model.start(question, language)
        sources: list[Source] = []
        records: list[ToolCallRecord] = []
        results: tuple[ToolResult, ...] = ()
        answer: AgentAnswer | None = None
        # Общий дедлайн ставится на ходы модели: это долгая часть, у инструментов свои таймауты.
        deadline = asyncio.get_running_loop().time() + MAX_REQUEST_SECONDS
        for step in range(1, MAX_STEPS + 1):
            try:
                async with asyncio.timeout_at(deadline):
                    turn = await conversation.next_turn(results)
            except TimeoutError:
                break
            submission = next((c for c in turn.calls if c.name == SUBMIT_ANSWER), None)
            if submission is not None:
                try:
                    answer = finalize(submission.args, sources, language, step)
                    break
                except InvalidSubmissionError as e:
                    # Кривой итог — как любой кривой вызов: модель видит ошибку и исправляется.
                    records.append(
                        ToolCallRecord(step, SUBMIT_ANSWER, submission.args, False, str(e), 0)
                    )
                    results = (ToolResult(SUBMIT_ANSWER, {"error": str(e)}, False),)
                    continue
            if not turn.calls:
                text = (turn.text or "").strip()
                answer = AgentAnswer(
                    text or NO_DATA_TEXT[language], language, not text, (), False, step
                )
                break
            results = tuple(
                [await self._run(step, call, viewer, sources, records) for call in turn.calls]
            )
        if answer is None:  # шаги или время кончились — сообщаем, что данных нет
            answer = AgentAnswer(NO_DATA_TEXT[language], language, True, (), False, step)

        run = AgentRun(
            user_id=viewer.user_id,
            question=question,
            answer=answer,
            tool_calls=tuple(records),
            latency_ms=round((time.perf_counter() - started) * 1000),
            model=conversation.model,
            prompt_version=self._model.prompt_version,
        )
        async with self._uow_factory() as uow:
            run_id = await uow.runs.add(run)
            await uow.commit()
        return AgentReply(run_id, answer, run.tool_calls)

    async def _run(
        self,
        step: int,
        call: ToolCall,
        viewer: AgentViewer,
        sources: list[Source],
        records: list[ToolCallRecord],
    ) -> ToolResult:
        """Выполняет один вызов. Любая проблема возвращается модели как результат-ошибка."""
        started = time.perf_counter()
        spec = DATA_TOOL_SPECS.get(call.name)
        error: str | None = None
        content: dict[str, Any] = {}
        if spec is None:
            error = f"Unknown tool: {call.name}"
        elif issues := validate(spec.parameters, call.args):
            error = "Invalid arguments: " + "; ".join(f"{i.field} {i.message}" for i in issues)
        else:
            try:
                content = await self._dispatch(call, viewer, sources)
            except DomainError as e:  # например, чужой или несуществующий отчёт — 404 модели
                error = str(e)
            except ServiceUnavailableError:
                error = "Tool is temporarily unavailable"
        latency_ms = round((time.perf_counter() - started) * 1000)
        records.append(ToolCallRecord(step, call.name, call.args, error is None, error, latency_ms))
        return ToolResult(call.name, {"error": error} if error else content, error is None)

    async def _dispatch(
        self, call: ToolCall, viewer: AgentViewer, sources: list[Source]
    ) -> dict[str, Any]:
        args = call.args
        if call.name == "search_procedures":
            query = str(args["query"])[:MAX_SEARCH_QUERY]
            found = await self._search.search(query, args.get("top_k", DEFAULT_SEARCH_TOP_K))
            numbered = [replace(s, number=len(sources) + n) for n, s in enumerate(found, 1)]
            sources.extend(numbered)
            return {
                "passages": [
                    {
                        "passage": s.number,
                        "document": s.title,
                        "section": s.section_path,
                        "text": s.text,
                    }
                    for s in numbered
                ]
            }
        if call.name == "list_reports":
            reports = await self._reports.list_reports(
                viewer, args.get("status"), args.get("template"), args.get("limit", 10)
            )
            return {"reports": reports}
        if call.name == "get_report":
            return {"report": await self._reports.get_report(viewer, args["report_id"])}
        if call.name == "get_report_template":
            return {"template": await self._reports.get_template(args["name"])}
        return {"document": await self._documents.active_version(args["title"])}
