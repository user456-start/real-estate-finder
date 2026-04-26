from __future__ import annotations

from fastapi import APIRouter
from langchain_core.messages import HumanMessage

from app.agents.chat import get_chat_agent
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat/message", response_model=ChatResponse)
async def chat_message(req: ChatRequest) -> ChatResponse:
    thread_id = req.thread_id or f"property:{req.property_id}"

    chat_agent = get_chat_agent()
    result = await chat_agent.ainvoke(
        {
            "messages": [HumanMessage(content=req.message)],
            "property_id": req.property_id,
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    messages = result.get("messages") or []
    reply = messages[-1].content if messages else ""
    return ChatResponse(reply=reply, thread_id=thread_id)
