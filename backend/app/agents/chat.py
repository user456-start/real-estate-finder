from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, Optional

import anthropic
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.config import settings
from app.tools.chat_tools import (
    get_property_details,
    google_places_search,
    nearby_places_tool,
    search_area_guides,
    search_more_listings,
)

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """You are a Dubai real-estate assistant with intent classification abilities.
Classify the user's question into ONE of these categories:

1. **property_details** - Questions about the specific property (price, size, amenities, lease terms)
2. **location_context** - Questions about the area/neighborhood (transport, schools, restaurants, vibe)
3. **nearby_comparison** - Questions comparing this property to nearby ones
4. **search_similar** - User wants to search for other properties like this one
5. **general_chat** - General conversation or clarification

Respond with a JSON object:
{
  "intent": "<one of the above>",
  "reasoning": "<brief explanation>",
  "query": "<the core question for tool use>"
}

Be strict about JSON format — ALWAYS return valid JSON only, no other text.""".strip()

SYNTHESIS_SYSTEM_PROMPT = """You are a Dubai real-estate assistant synthesizing tool outputs into helpful answers.
Given the user's original question, tool results, and property context, provide a clear, concise response.

Guidelines:
- Acknowledge what the tools found
- If `google_places` results are present, use them as the primary source for specific named places
  (restaurants, supermarkets, malls). Always include the distance_m converted to km or a walking/driving
  estimate (≤1 km walk ≈ 10-15 min, 1-5 km drive ≈ 5-10 min, 5-15 km drive ≈ 15-25 min).
- If results are insufficient, suggest what else to check
- Keep responses under 3-4 sentences unless more detail is needed
- Reference specific data (prices, distances, areas) when available
- Be honest about limitations in the data""".strip()


class ChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    property_id: Optional[str]
    intent: Optional[str]
    tool_results: Optional[dict[str, Any]]
    user_query: Optional[str]


_graph = None


def get_chat_agent():
    """Return a compiled LangGraph chat agent with routing and synthesis."""
    global _graph
    if _graph is not None:
        return _graph

    async def route_intent(state: ChatState) -> dict[str, Any]:
        """Classify user intent and extract query."""
        messages = state.get("messages") or []
        if not messages:
            return {"intent": "general_chat", "user_query": ""}
        
        # Get the last user message
        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break
        
        if not last_user_msg:
            return {"intent": "general_chat", "user_query": ""}
        
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=ROUTER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": last_user_msg}],
            )
            
            result_text = response.content[0].text.strip()

            # Claude sometimes wraps JSON in ```json ... ``` fences — extract the object
            json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
            if not json_match:
                raise json.JSONDecodeError("No JSON object found", result_text, 0)
            result = json.loads(json_match.group())
            intent = result.get("intent", "general_chat")
            query = result.get("query", last_user_msg)
            
            return {
                "intent": intent,
                "user_query": query,
            }
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Intent routing failed: {e}, defaulting to general_chat")
            return {
                "intent": "general_chat",
                "user_query": last_user_msg,
            }

    async def fetch_tools(state: ChatState) -> dict[str, Any]:
        """Fetch results from appropriate tools based on intent."""
        intent = state.get("intent", "general_chat")
        query = state.get("user_query", "")
        property_id = state.get("property_id") or "unknown"

        tool_results = {}

        try:
            # Always fetch property details
            prop_details = await get_property_details(property_id)
            tool_results["property_details"] = prop_details

            # Try RAG tools, but fail gracefully if embeddings unavailable
            try:
                if intent == "property_details":
                    pass  # property_details already fetched above

                elif intent == "location_context":
                    area_guides = await search_area_guides(query)
                    tool_results["area_guides"] = area_guides
                    nearby = await nearby_places_tool(property_id, radius_meters=1500)
                    tool_results["nearby_places"] = nearby
                    # Live Google Places search for specific named places
                    coords = prop_details.get("coordinates")
                    if coords:
                        gplaces = await google_places_search(
                            query=query,
                            lat=coords["lat"],
                            lon=coords["lon"],
                        )
                        tool_results["google_places"] = gplaces

                elif intent == "nearby_comparison":
                    nearby = await nearby_places_tool(property_id, radius_meters=1500)
                    tool_results["nearby_places"] = nearby
                    coords = prop_details.get("coordinates")
                    if coords:
                        gplaces = await google_places_search(
                            query=query,
                            lat=coords["lat"],
                            lon=coords["lon"],
                        )
                        tool_results["google_places"] = gplaces

                elif intent == "search_similar":
                    similar = await search_more_listings(query, top_k=5)
                    tool_results["search_results"] = similar
            except Exception as rag_err:
                # RAG/embedding failed but we still have property details
                logger.warning(f"RAG tool skipped ({intent}): {rag_err}")
                tool_results["rag_unavailable"] = str(rag_err)

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            tool_results["error"] = str(e)

        return {"tool_results": tool_results}

    async def synthesize_response(state: ChatState) -> dict[str, Any]:
        """Synthesize tool results and user context into a final answer."""
        messages = state.get("messages") or []
        tool_results = state.get("tool_results") or {}
        property_id = state.get("property_id") or "unknown"
        user_query = state.get("user_query", "")
        
        # Get the original user message
        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break
        
        # Build context for synthesis
        context_str = f"""
Property ID: {property_id}
User Question: {last_user_msg}
Tool Results: {json.dumps(tool_results, default=str, indent=2)}
""".strip()
        
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYNTHESIS_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": context_str},
                ],
            )
            
            reply = response.content[0].text
            return {"messages": [AIMessage(content=reply)]}
        
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            fallback = f"I encountered an issue processing your question. Please try again or check the listing details directly. (Error: {e})"
            return {"messages": [AIMessage(content=fallback)]}

    # Build the graph
    g: StateGraph = StateGraph(ChatState)
    
    g.add_node("route_intent", route_intent)
    g.add_node("fetch_tools", fetch_tools)
    g.add_node("synthesize", synthesize_response)
    
    g.set_entry_point("route_intent")
    g.add_edge("route_intent", "fetch_tools")
    g.add_edge("fetch_tools", "synthesize")
    g.add_edge("synthesize", END)
    
    _graph = g.compile(checkpointer=MemorySaver())
    return _graph
