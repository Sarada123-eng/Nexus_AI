from backend import initialize_chatbot, tools
from langchain_core.messages import HumanMessage

print('tools:', [getattr(t,'name',None) or getattr(t,'func',None) for t in tools])
bot = initialize_chatbot()
state = {"messages": [{"type":"human","content":"Call the calculator tool with JSON: {\"first_num\":4, \"second_num\":56, \"operation\": \"*\"} and return only the numeric result."}]}
try:
    resp = bot.invoke(state, config={"configurable":{"thread_id":"smoke-calc-star"}})
    print('invoke done, messages:')
    for m in resp.get('messages', []):
        print(type(m), getattr(m,'content',None), getattr(m,'tool_calls',None))
except Exception as e:
    import traceback
    print('invoke error:', repr(e))
    traceback.print_exc()
