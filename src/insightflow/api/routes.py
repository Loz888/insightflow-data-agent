import asyncio
from fastapi import APIRouter, HTTPException, Request
from insightflow.api.schemas import ChatRequest, ChatResponse
from insightflow.agent.cancellation import Cancellation
from insightflow.database.errors import AgentError

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request):
    service = request.app.state.service
    if service is None:
        raise HTTPException(503, "Database configuration required for local chat")
    token = Cancellation()
    worker = asyncio.create_task(
        asyncio.to_thread(service.run, body.question, body.session_id, cancellation=token)
    )
    try:
        while not worker.done():
            if await request.is_disconnected():
                token.cancel()
                try:
                    await asyncio.shield(worker)
                except AgentError:
                    pass
                raise HTTPException(499, detail={"kind": "REQUEST_CANCELLED", "message": "客户端已断开。"})
            await asyncio.wait({worker}, timeout=0.02)
        result = await worker
    except asyncio.CancelledError:
        token.cancel()
        try:
            await asyncio.shield(worker)
        except AgentError:
            pass
        raise
    except AgentError as exc:
        raise HTTPException(
            499 if exc.kind.value == "REQUEST_CANCELLED" else 503, detail=exc.as_dict()
        ) from None
    return {
        **result["final_answer"],
        "error": result.get("error"),
        "request_id": result["request_id"],
        "retries": result["retry_count"],
        "model_type": service.provider.model_type,
    }
