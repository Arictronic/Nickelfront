"""
RAG Chain - сервис для генерации ответов на основе векторного поиска.
"""

import logging
from typing import Any

from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document

from app.services.qwen_client import get_qwen_client
from app.services.rag_vector_store import get_rag_vector_store

logger = logging.getLogger(__name__)


RAG_PROMPT_TEMPLATE = """
Ты - эксперт по материалам и анализу научных документов.
Используй только данные из контекста.

Контекст:
{context}

Вопрос:
{question}

Требования:
1. Отвечай на русском языке.
2. Если данных недостаточно, явно скажи об этом.
3. Дай краткий вывод и затем детали.

Ответ:
""".strip()


class RAGChain:
    def __init__(self, search_k: int = 4, max_tokens: int = 1024):
        self.search_k = search_k
        self.max_tokens = max_tokens
        self._chain: RetrievalQA | None = None
        self._vector_store = None
        logger.info("Инициализация RAGChain: search_k=%s, max_tokens=%s", search_k, max_tokens)

    def _get_vector_store(self):
        if self._vector_store is None:
            self._vector_store = get_rag_vector_store()
        return self._vector_store

    def _get_prompt_template(self) -> PromptTemplate:
        return PromptTemplate(template=RAG_PROMPT_TEMPLATE, input_variables=["context", "question"])

    def _build_chain(self) -> RetrievalQA | None:
        logger.debug("Построение RAG-цепи")

        vector_store_manager = self._get_vector_store()
        if vector_store_manager is None:
            logger.error("Векторное хранилище не инициализировано")
            return None

        # IMPORTANT: manager -> actual LangChain Chroma store
        langchain_vector_store = vector_store_manager.get_vector_store()
        if langchain_vector_store is None:
            logger.error("LangChain vector store не инициализирован")
            return None

        retriever = langchain_vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": self.search_k},
        )

        chain = RetrievalQA.from_chain_type(
            llm=self._get_llm(),
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": self._get_prompt_template()},
        )

        logger.debug("RAG-цепь успешно построена")
        return chain

    def _get_llm(self):
        from langchain.callbacks.manager import CallbackManagerForLLMRun
        from langchain.schema import Generation, LLMResult
        from langchain_community.llms import BaseLLM

        class QwenLLM(BaseLLM):
            client: Any = None
            max_tokens: int = 1024

            @property
            def _llm_type(self) -> str:
                return "qwen"

            def _call(
                self,
                prompt: str,
                stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None,
                **kwargs: Any,
            ) -> str:
                if self.client is None:
                    return "Ошибка: Qwen клиент не инициализирован"

                result = self.client.send_message(
                    message=prompt,
                    thinking_enabled=False,
                    search_enabled=False,
                    auto_continue=False,
                )

                if result.get("error"):
                    return f"Ошибка: {result.get('error')}"

                return result.get("response", "")

            def _generate(
                self,
                prompts: list[str],
                stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None,
                **kwargs: Any,
            ) -> LLMResult:
                generations = []
                for prompt in prompts:
                    text = self._call(
                        prompt=prompt,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    )
                    generations.append([Generation(text=text)])
                return LLMResult(generations=generations)

        qwen_client = get_qwen_client()
        return QwenLLM(client=qwen_client, max_tokens=self.max_tokens)

    def get_chain(self) -> RetrievalQA | None:
        if self._chain is None:
            self._chain = self._build_chain()
        return self._chain

    def query(self, question: str) -> dict[str, Any]:
        logger.info("Обработка запроса: %s...", question[:80])

        chain = self.get_chain()
        if chain is None:
            return {
                "error": "RAG цепь не инициализирована",
                "result": "",
                "query": question,
                "source_documents": [],
            }

        try:
            result = chain.invoke({"query": question})
            response = {
                "query": question,
                "result": result.get("result", ""),
                "source_documents": self._format_source_documents(result.get("source_documents", [])),
            }
            logger.info("Запрос обработан, найдено источников: %s", len(response["source_documents"]))
            return response
        except Exception as e:
            logger.error("Ошибка при обработке запроса: %s", e, exc_info=True)
            return {
                "error": str(e),
                "result": "",
                "query": question,
                "source_documents": [],
            }

    def _format_source_documents(self, documents: list[Document]) -> list[dict[str, Any]]:
        formatted = []
        for i, doc in enumerate(documents, 1):
            formatted.append({
                "index": i,
                "content": doc.page_content[:500],
                "metadata": doc.metadata,
            })
        return formatted


rag_chain = RAGChain()


def process_query(question: str) -> dict[str, Any]:
    return rag_chain.query(question)
