from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Protocol
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from chromadb import PersistentClient
from langchain_core.messages import SystemMessage, HumanMessage
import pdfplumber
from docx import Document


class UploadedFile(Protocol):
    name: str

    def getvalue(self) -> bytes:
        ...


def extract_text(uploaded_file: UploadedFile) -> str:
    file_name = uploaded_file.name.lower()
    file_bytes = uploaded_file.getvalue()

    if file_name.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="ignore")

    elif file_name.endswith(".pdf"):
        text_parts = []
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)

    elif file_name.endswith(".docx"):
        doc = Document(BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    else:
        raise ValueError("Unsupported file type. Please upload a TXT, PDF, or DOCX file.")
    

def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    return splitter.split_text(text)

@lru_cache(maxsize=1)
def init_embedding():
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

@lru_cache(maxsize=None)
def init_vectorstore(persist_dir: str = "./chroma_db"):
    resolved_persist_dir = str(Path(persist_dir).resolve())
    client = PersistentClient(path=resolved_persist_dir)
    collection = client.get_or_create_collection(name="documents")
    return collection

def upsert_document(
    uploaded_file: UploadedFile,
    collection,
    embedding_model,
    doc_id: str | None = None,
) -> str:
    if doc_id is None:
        doc_id = str(uuid.uuid4())

    text = extract_text(uploaded_file)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"Document '{uploaded_file.name}' contains no indexable text.")

    for i, chunk in enumerate(chunks):
        embedding = embedding_model.encode(chunk)
        collection.upsert(
            ids=[f"{doc_id}_{i}"],
            embeddings=[embedding],
            metadatas=[{
                "source": uploaded_file.name,
                "chunk_index": i,
                "doc_id": doc_id
            }],
            documents=[chunk]
        )

    return doc_id
    

def retrieve_similar_chunks(query: str, collection, embedding_model, top_k: int = 5, doc_id: str = None) -> list[dict]:
    query_embedding = embedding_model.encode(query)
    
    where_filter = {"doc_id": doc_id} if doc_id else None
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )
    
    retrieved_chunks = []
    if results["documents"]:
        for doc, metadata, distance in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
            retrieved_chunks.append({
                "text": doc,
                "metadata": metadata,
                "distance": distance
            })
    
    return retrieved_chunks

def answer_with_context(query: str, retrieved_chunks: list, chatbot) -> str:
    if not retrieved_chunks:
        return "No relevant information found in the indexed documents."
    
    context = "\n\n".join([
        f"[Source: {chunk['metadata']['source']} - Chunk {chunk['metadata']['chunk_index']}]\n{chunk['text']}"
        for chunk in retrieved_chunks
    ])
    
    system_prompt = (
        "You are a helpful assistant that answers questions based ONLY on the provided document excerpts. "
        "If the answer is not in the documents, say you don't know."
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Document excerpts:\n\n{context}\n\nUser question: {query}")
    ]
    
    # Return the stream iterator so the frontend can consume tokens progressively
    return chatbot.stream({"messages": messages}, config={'configurable': {'thread_id': 'rag'}}, stream_mode="messages")
