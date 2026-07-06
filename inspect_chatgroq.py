from langchain_groq import ChatGroq
print([a for a in dir(ChatGroq) if not a.startswith('_')])
