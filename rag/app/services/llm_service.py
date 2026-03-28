"""
Модуль работы с LLM через API.

Предоставляет обёртку для вызова внешних LLM (OpenAI-compatible API)
с поддержкой настройки параметров генерации и обработки ошибок.
"""

import logging

from langchain_community.llms import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Сервис для работы с LLM через API.

    Предоставляет интерфейс для генерации текстов с использованием
    внешних LLM (OpenAI или совместимые API). Поддерживает кэширование
    экземпляра модели и обработку ошибок сети.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ):
        """
        Инициализация LLM сервиса.

        Args:
            api_key: API ключ для доступа к LLM. Если не указан,
                берётся из настроек.
            base_url: Базовый URL API. Если не указан, берётся из настроек.
            model_name: Название модели. Если не указано, берётся из настроек.
        """
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_api_base_url
        self.model_name = model_name or settings.llm_model_name

        self._llm: OpenAI | None = None

        logger.info(
            f"Инициализация LLMService: model={self.model_name}, "
            f"base_url={self.base_url}"
        )

        # Проверка наличия API ключа
        if not self.api_key:
            logger.warning("API ключ LLM не установлен. Генерация будет недоступна.")

    def _create_llm(
        self,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        streaming: bool = False,
    ) -> OpenAI:
        """
        Создаёт экземпляр LLM с заданными параметрами.

        Args:
            temperature: Температура генерации (0.0-2.0). Низкие значения
                дают более детерминированные ответы.
            max_tokens: Максимальное количество токенов в ответе.
            streaming: Включить потоковую генерацию.

        Returns:
            OpenAI: Инициализированная модель LLM.
        """
        logger.debug(
            f"Создание LLM: temperature={temperature}, max_tokens={max_tokens}"
        )

        llm = OpenAI(
            model=self.model_name,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            request_timeout=60,
            max_retries=2,
        )

        logger.debug("LLM успешно создана")
        return llm

    def get_llm(
        self,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> OpenAI:
        """
        Возвращает экземпляр LLM (создаёт при первом вызове).

        Args:
            temperature: Температура генерации.
            max_tokens: Максимальное количество токенов.

        Returns:
            OpenAI: Инициализированная модель LLM.
        """
        if self._llm is None:
            self._llm = self._create_llm(
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self._llm

    def generate(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """
        Генерирует ответ на промт через LLM API.

        Args:
            prompt: Текст промта для генерации.
            temperature: Температура генерации.
            max_tokens: Максимальное количество токенов.

        Returns:
            str: Сгенерированный текст.

        Raises:
            ValueError: Если API ключ не установлен.
            RuntimeError: Если произошла ошибка при вызове API.

        Example:
            >>> llm_service = LLMService()
            >>> response = llm_service.generate("Расскажи о суперсплавах")
        """
        if not self.api_key:
            logger.error("Попытка генерации без API ключа")
            raise ValueError("API ключ LLM не установлен")

        logger.info(f"Генерация ответа для промта длиной {len(prompt)} символов")

        try:
            llm = self._create_llm(
                temperature=temperature,
                max_tokens=max_tokens,
            )

            response = llm.invoke(prompt)
            logger.info(f"Генерация завершена, ответ длиной {len(response)} символов")
            return response

        except Exception as e:
            logger.error(f"Ошибка при генерации через LLM API: {e}")
            raise RuntimeError(f"Не удалось сгенерировать ответ: {e}")

    def generate_stream(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        """
        Генерирует ответ с потоковой передачей токенов.

        Args:
            prompt: Текст промта для генерации.
            temperature: Температура генерации.
            max_tokens: Максимальное количество токенов.

        Yields:
            GenerationChunk: Фрагменты сгенерированного текста.

        Example:
            >>> for chunk in llm_service.generate_stream("Расскажи о сплавах"):
            ...     print(chunk.text, end="", flush=True)
        """
        if not self.api_key:
            raise ValueError("API ключ LLM не установлен")

        logger.info(f"Потоковая генерация для промта длиной {len(prompt)} символов")

        try:
            llm = self._create_llm(
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=True,
            )

            yield from llm.stream(prompt)

        except Exception as e:
            logger.error(f"Ошибка при потоковой генерации: {e}")
            raise RuntimeError(f"Не удалось выполнить потоковую генерацию: {e}")

    def is_available(self) -> bool:
        """
        Проверяет доступность LLM сервиса.

        Returns:
            bool: True если API ключ установлен и сервис готов к работе.
        """
        return bool(self.api_key)


# Глобальный экземпляр LLM сервиса
llm_service = LLMService()


def create_llm(
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> OpenAI:
    """
    Создаёт и возвращает экземпляр LLM для использования в LangChain цепях.

    Args:
        temperature: Температура генерации.
        max_tokens: Максимальное количество токенов.

    Returns:
        OpenAI: Инициализированная модель LLM.
    """
    return llm_service.get_llm(
        temperature=temperature,
        max_tokens=max_tokens,
    )
