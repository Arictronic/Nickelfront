"""
RAG Chain — сервис для генерации ответов на основе векторного поиска.

Использует LangChain для построения RAG-цепи:
1. Поиск релевантных документов в векторной базе
2. Формирование промта с контекстом
3. Генерация ответа через Qwen API
"""

import logging
from typing import Any

from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document

from app.services.qwen_client import get_qwen_client
from app.services.rag_vector_store import get_rag_vector_store

logger = logging.getLogger(__name__)


# Промт для RAG-цепи, специализированный для патентов на суперсплавы
RAG_PROMPT_TEMPLATE = """
Ты — эксперт в области материаловедения и металлургии, специализирующийся
на суперсплавах и патентном анализе. Твоя задача — отвечать на вопросы
пользователей, основываясь на предоставленном контексте из патентных документов.

Контекст из патентных документов:
{context}

Вопрос пользователя:
{question}

Инструкции для ответа:
1. Отвечай ТОЛЬКО на основе предоставленного контекста из патентов.
2. Если в контексте нет информации для ответа, скажи: "В доступных патентных документах нет информации по этому вопросу."
3. Цитируй конкретные детали из контекста (состав сплава, температуры, свойства).
4. Используй техническую терминологию правильно (легирующие элементы, фазы, термообработка).
5. Если упоминаются конкретные марки сплавов или патенты, укажи их.
6. Отвечай на русском языке, сохраняя научный стиль.
7. Структурируй ответ: сначала краткий ответ, затем детали.

Ответ:
""".strip()


class RAGChain:
    """
    Класс для управления RAG-цепью (Retrieval-Augmented Generation).

    Инкапсулирует логику поиска релевантных документов в векторной базе
    и генерации ответа на основе найденного контекста с помощью Qwen API.
    """

    def __init__(
        self,
        search_k: int = 4,
        max_tokens: int = 1024,
    ):
        """
        Инициализация RAG-цепи.

        Args:
            search_k: Количество документов для поиска.
            max_tokens: Максимальное количество токенов в ответе.
        """
        self.search_k = search_k
        self.max_tokens = max_tokens

        self._chain: RetrievalQA | None = None
        self._vector_store = None

        logger.info(
            f"Инициализация RAGChain: search_k={self.search_k}, "
            f"max_tokens={self.max_tokens}"
        )

    def _get_vector_store(self):
        """Получить векторное хранилище RAG."""
        if self._vector_store is None:
            self._vector_store = get_rag_vector_store()
        return self._vector_store

    def _get_prompt_template(self) -> PromptTemplate:
        """Создать шаблон промта для RAG-цепи."""
        return PromptTemplate(
            template=RAG_PROMPT_TEMPLATE,
            input_variables=["context", "question"],
        )

    def _build_chain(self) -> RetrievalQA | None:
        """
        Построить RAG-цепь LangChain.

        Returns:
            RetrievalQA: Готовая RAG-цепь или None при ошибке.
        """
        logger.debug("Построение RAG-цепи")

        vector_store = self._get_vector_store()
        if vector_store is None:
            logger.error("Векторное хранилище не инициализировано")
            return None

        # Создание retriever
        retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": self.search_k},
        )

        # Создание RAG-цепи
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
        """
        Получить LLM для генерации ответов.

        Использует Qwen через HTTP API.
        """
        from typing import Any

        from langchain.callbacks.manager import CallbackManagerForLLMRun
        from langchain_community.llms import BaseLLM

        class QwenLLM(BaseLLM):
            """Обёртка Qwen API для LangChain."""

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
                """Вызвать Qwen API."""
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

        qwen_client = get_qwen_client()
        return QwenLLM(client=qwen_client, max_tokens=self.max_tokens)

    def get_chain(self) -> RetrievalQA | None:
        """Возвращает RAG-цепь (создаёт при первом вызове)."""
        if self._chain is None:
            self._chain = self._build_chain()
        return self._chain

    def query(self, question: str) -> dict[str, Any]:
        """
        Обрабатывает вопрос пользователя через RAG-цепь.

        Args:
            question: Текст вопроса пользователя.

        Returns:
            Dict[str, Any]: Словарь с результатами.
        """
        logger.info(f"Обработка запроса: {question[:50]}...")

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
                "source_documents": self._format_source_documents(
                    result.get("source_documents", [])
                ),
            }

            logger.info(
                f"Запрос обработан, найдено источников: {len(response['source_documents'])}"
            )
            return response

        except Exception as e:
            logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
            return {
                "error": str(e),
                "result": "",
                "query": question,
                "source_documents": [],
            }

    def _format_source_documents(
        self, documents: list[Document]
    ) -> list[dict[str, Any]]:
        """Форматирует документы-источники для ответа."""
        formatted = []
        for i, doc in enumerate(documents, 1):
            formatted.append({
                "index": i,
                "content": doc.page_content[:500],
                "metadata": doc.metadata,
            })
        return formatted


# Глобальный экземпляр RAG-цепи
rag_chain = RAGChain()


def process_query(question: str) -> dict[str, Any]:
    """Обработать вопрос через глобальную RAG-цепь."""
    return rag_chain.query(question)
