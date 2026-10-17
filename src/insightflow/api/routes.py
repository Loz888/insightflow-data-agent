from fastapi import APIRouter, HTTPException, Request
from insightflow.api.schemas import ChatRequest, ChatResponse
from insightflow.database.errors import AgentError

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request):
    service = request.app.state.service
    if service is None:
        raise HTTPException(503, "Database configuration required for local chat")
    try:
        result = service.run(body.question, body.session_id)
    except AgentError as exc:
        raise HTTPException(503, detail=exc.as_dict()) from None
    return {
        **result["final_answer"],
        "error": result.get("error"),
        "request_id": result["request_id"],
        "retries": result["retry_count"],
        "model_type": service.provider.model_type,
    }
