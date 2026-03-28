"""
Модуль сборки RAG-цепи LangChain.

Реализует полный пайплайн Retrieval-Augmented Generation:
приём запроса, поиск релевантных документов, формирование промта,
генерация ответа через LLM API.
"""

import logging
from typing import Any

from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document

from app.config import settings
from app.core.vector_store import vector_store_manager
from app.services.llm_service import create_llm

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
    и генерации ответа на основе найденного контекста с помощью LLM.
    """

    def __init__(
        self,
        search_k: int | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        """
        Инициализация RAG-цепи.

        Args:
            search_k: Количество документов для поиска. По умолчанию из настроек.
            temperature: Температура генерации LLM (0.0-1.0). Низкое значение
                для более детерминированных ответов.
            max_tokens: Максимальное количество токенов в ответе.
        """
        self.search_k = search_k or settings.search_k
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._llm: Any | None = None
        self._chain: RetrievalQA | None = None

        logger.info(
            f"Инициализация RAGChain: search_k={self.search_k}, "
            f"temperature={self.temperature}, max_tokens={self.max_tokens}"
        )

    def _get_llm(self) -> Any:
        """
        Возвращает или создаёт LLM для генерации ответов.

        Returns:
            Any: Инициализированная LLM (OpenAI-compatible).
        """
        if self._llm is None:
            self._llm = create_llm(
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        return self._llm

    def _get_prompt_template(self) -> PromptTemplate:
        """
        Создаёт шаблон промта для RAG-цепи.

        Returns:
            PromptTemplate: Шаблон промта с инструкциями для патентного анализа.
        """
        return PromptTemplate(
            template=RAG_PROMPT_TEMPLATE,
            input_variables=["context", "question"],
        )

    def _build_chain(self) -> RetrievalQA:
        """
        Строит RAG-цепь LangChain.

        Комбинирует векторное хранилище, модель эмбеддингов, LLM и промт
        в единую цепь для обработки запросов.

        Returns:
            RetrievalQA: Готовая RAG-цепь для обработки запросов.
        """
        logger.debug("Построение RAG-цепи")

        # Получение компонентов
        vector_store = vector_store_manager.get_vector_store()
        llm = self._get_llm()
        prompt = self._get_prompt_template()

        # Создание retriever с настройками поиска
        retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": self.search_k},
        )

        # Создание RAG-цепи
        chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": prompt},
        )

        logger.debug("RAG-цепь успешно построена")
        return chain

    def get_chain(self) -> RetrievalQA:
        """
        Возвращает RAG-цепь (создаёт при первом вызове).

        Returns:
            RetrievalQA: Инициализированная RAG-цепь.
        """
        if self._chain is None:
            self._chain = self._build_chain()
        return self._chain

    def query(self, question: str) -> dict[str, Any]:
        """
        Обрабатывает вопрос пользователя через RAG-цепь.

        Выполняет поиск релевантных документов и генерирует ответ
        на основе найденного контекста.

        Args:
            question: Текст вопроса пользователя.

        Returns:
            Dict[str, Any]: Словарь с результатами:
                - query: Исходный вопрос
                - result: Сгенерированный ответ
                - source_documents: Список документов-источников

        Raises:
            RuntimeError: Если произошла ошибка при обработке запроса.

        Example:
            >>> rag = RAGChain()
            >>> result = rag.query("Какой состав у сплава ХН77ТЮР?")
            >>> print(result['result'])
        """
        logger.info(f"Обработка запроса: {question[:50]}...")

        try:
            chain = self.get_chain()
            result = chain.invoke({"query": question})

            # Форматирование результата
            response = {
                "query": question,
                "result": result.get("result", ""),
                "source_documents": self._format_source_documents(
                    result.get("source_documents", [])
                ),
            }

            logger.info(f"Запрос обработан, найдено источников: {len(response['source_documents'])}")
            return response

        except Exception as e:
            logger.error(f"Ошибка при обработке запроса: {e}")
            raise RuntimeError(f"Не удалось обработать запрос: {e}")

    def _format_source_documents(
        self, documents: list[Document]
    ) -> list[dict[str, Any]]:
        """
        Форматирует документы-источники для ответа.

        Args:
            documents: Список документов LangChain.

        Returns:
            List[Dict[str, Any]]: Список отформатированных документов
                с содержанием и метаданными.
        """
        formatted = []
        for i, doc in enumerate(documents, 1):
            formatted.append({
                "index": i,
                "content": doc.page_content[:500],  # Ограничение длины
                "metadata": doc.metadata,
            })
        return formatted

    def query_with_sources(
        self,
        question: str,
        include_scores: bool = False,
    ) -> dict[str, Any]:
        """
        Обрабатывает вопрос с дополнительной информацией об источниках.

        Args:
            question: Текст вопроса пользователя.
            include_scores: Включить оценки релевантности документов.

        Returns:
            Dict[str, Any]: Развёрнутый ответ с информацией об источниках.
        """
        logger.info(f"Обработка запроса с источниками: {question[:50]}...")

        # Поиск документов
        if include_scores:
            search_results = vector_store_manager.similarity_search_with_score(
                question, k=self.search_k
            )
            documents = [doc for doc, _ in search_results]
            scores = [float(score) for _, score in search_results]
        else:
            documents = vector_store_manager.similarity_search(
                question, k=self.search_k
            )
            scores = None

        # Генерация ответа
        result = self.query(question)

        # Добавление информации об источниках
        if scores:
            for i, doc_info in enumerate(result["source_documents"]):
                if i < len(scores):
                    doc_info["relevance_score"] = scores[i]

        result["documents_found"] = len(documents)
        return result


# Глобальный экземпляр RAG-цепи
rag_chain = RAGChain()


def process_query(question: str) -> dict[str, Any]:
    """
    Обрабатывает вопрос пользователя через глобальную RAG-цепь.

    Args:
        question: Текст вопроса пользователя.

    Returns:
        Dict[str, Any]: Словарь с результатами обработки.
    """
    return rag_chain.query(question)


def process_query_with_sources(
    question: str,
    include_scores: bool = False,
) -> dict[str, Any]:
    """
    Обрабатывает вопрос с информацией об источниках.

    Args:
        question: Текст вопроса пользователя.
        include_scores: Включить оценки релевантности.

    Returns:
        Dict[str, Any]: Развёрнутый ответ с источниками.
    """
    return rag_chain.query_with_sources(question, include_scores)
