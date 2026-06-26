import asyncio
from app.logger import setup_logger
setup_logger()

from langchain_core.messages import HumanMessage
from app.agents.state import create_initial_state
from app.agents.graph import build_graph

graph = build_graph(checkpointer = None)
state = create_initial_state("sess_test_001")
state["messages"] = [HumanMessage(content = "I think I'm having a heart attack")]

result = asyncio.run(graph.ainvoke(state))
print(result["is_emergency"])

print("------------------------------------------------------")
for m in result["messages"]:
    print(type(m).__name__, "->", m.content)