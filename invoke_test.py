from backend import initialize_chatbot, tools

print('tools count:', len(tools))
for t in tools:
    print('tool name attr sample:', getattr(t, 'name', getattr(t, 'func', repr(t))))

bot = initialize_chatbot()
state = {"messages": [{"type": "human", "content": "What is today's IPL match result? Please use search if needed."}]}
try:
    resp = bot.invoke(state, config={"configurable": {"thread_id": "invoke-test-thread"}})
    print('invoke resp (messages count):', len(resp.get('messages', [])))
    for m in resp.get('messages', []):
        print(type(m), getattr(m, 'content', None), getattr(m, 'tool_calls', None))
except Exception as e:
    import traceback, sys
    print('invoke error:', repr(e))
    traceback.print_exc()
