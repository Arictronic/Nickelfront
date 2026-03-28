import polars as pl
from datetime import date


def validate_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Проверка колонок и приведение типов. Возвращает исправленный DataFrame."""
    required_columns = {
        "patent_id": pl.Utf8,
        "title": pl.Utf8,
        "date": pl.Utf8,
        "category": pl.Utf8,
        "applicant": pl.Utf8,
        "country": pl.Utf8,
    }

    for col, dtype in required_columns.items():
        if col not in df.columns:
            raise ValueError(f"Отсутствует обязательная колонка: {col}")
        if df[col].dtype != dtype:
            try:
                df = df.with_columns(pl.col(col).cast(dtype))
            except Exception as e:
                raise TypeError(
                    f"Колонка {col} не может быть приведена к {dtype}: {e}"
                )
    return df


def validate_dates(df: pl.DataFrame) -> pl.DataFrame:
    """Парсинг дат и предупреждение о некорректных значениях."""
    df = df.with_columns(
        pl.col("date")
        .str.strptime(pl.Date, "%Y-%m-%d", strict=False)
        .alias("date_parsed"),
    )

    invalid = df.filter(pl.col("date_parsed").is_null())
    if not invalid.is_empty():
        print(f"Предупреждение: {invalid.height} записей с некорректной датой")

    return df.drop("date").rename({"date_parsed": "date"})


def validate_patent_id(df: pl.DataFrame) -> pl.DataFrame:
    """Проверка формата patent_id (две заглавные буквы + 8 цифр)."""
    pattern = r"^[A-Z]{2}\d{8}$"
    df = df.with_columns(pl.col("patent_id").str.contains(pattern).alias("__valid_id"))
    invalid = df.filter(~pl.col("__valid_id"))
    if not invalid.is_empty():
        print(f"Предупреждение: {invalid.height} записей с некорректным patent_id")
    return df.drop("__valid_id")


def validate_country(df: pl.DataFrame) -> pl.DataFrame:
    """Проверка, что код страны — две заглавные буквы."""
    df = df.with_columns(
        pl.col("country").str.contains(r"^[A-Z]{2}$").alias("__valid_country")
    )
    invalid = df.filter(~pl.col("__valid_country"))
    if not invalid.is_empty():
        print(f"Предупреждение: {invalid.height} записей с некорректным кодом страны")
    return df.drop("__valid_country")


def check_completeness(df: pl.DataFrame) -> pl.DataFrame:
    """Возвращает DataFrame с процентами заполненности каждой колонки."""
    null_counts = df.null_count()  # Одна строка, колонки как в df
    completeness = (df.height - null_counts) / df.height * 100
    return completeness.unpivot(
        variable_name="column", value_name="completeness_%"
    )


# === Основной конвейер обработки ===

df = (
    df_raw
    .pipe(validate_schema)
    .pipe(validate_dates)
    .pipe(validate_patent_id)
    .pipe(validate_country)
)

print("\nПосле валидации (df):")
print(df)

# Дубликаты по patent_id
duplicates_count = df.filter(pl.col("patent_id").is_duplicated()).height
print(f"Количество дублированных записей (по patent_id): {duplicates_count}")

df = df.unique(subset=["patent_id"], keep="first")
print(f"Размер после удаления дубликатов: {df.height} записей")

# Полнота данных
completeness_df = check_completeness(df)
print("\nПолнота данных:")
print(completeness_df)

# Удаление записей без patent_id
critical = df.filter(pl.col("patent_id").is_null())
if not critical.is_empty():
    print(f"Обнаружено {critical.height} записей без patent_id – они будут удалены")
    df = df.filter(pl.col("patent_id").is_not_null())

# Заполнение пропусков
df = df.with_columns(
    pl.col("title").fill_null("Unknown"),
    pl.col("category").fill_null("Other"),
    pl.col("applicant").fill_null("Unknown"),
    pl.col("country").fill_null("Unknown"),
)

