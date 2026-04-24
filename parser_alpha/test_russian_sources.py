#!/usr/bin/env python3
"""
Тестирование российских источников (CyberLeninka и eLibrary)
"""
import asyncio
import json
from parsers_pkg.source_executor import execute_source_search

async def test_cyberleninka():
    """Тест CyberLeninka"""
    print("\n" + "="*60)
    print("ТЕСТ: CyberLeninka")
    print("="*60)
    
    query = "машинное обучение"
    print(f"\nЗапрос: '{query}'")
    print("Источник: cyberleninka")
    print("Лимит: 5 статей\n")
    
    try:
        results = await execute_source_search(
            query=query,
            source="cyberleninka",
            limit=5
        )
        
        print(f"✓ Найдено статей: {len(results)}")
        
        if results:
            print("\nПример первой статьи:")
            first = results[0]
            print(f"  Название: {first.get('title', 'N/A')[:80]}...")
            print(f"  Авторы: {', '.join(first.get('authors', []))[:60]}...")
            print(f"  Год: {first.get('year', 'N/A')}")
            print(f"  URL статьи: {first.get('article_url', 'N/A')}")
            print(f"  PDF URL: {first.get('pdf_url', 'N/A')}")
            
            # Сохраняем результаты
            with open('test_cyberleninka_results.json', 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print("\n✓ Результаты сохранены в test_cyberleninka_results.json")
        else:
            print("⚠ Статьи не найдены")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def test_elibrary():
    """Тест eLibrary"""
    print("\n" + "="*60)
    print("ТЕСТ: eLibrary")
    print("="*60)
    
    query = "искусственный интеллект"
    print(f"\nЗапрос: '{query}'")
    print("Источник: elibrary")
    print("Лимит: 5 статей\n")
    
    try:
        results = await execute_source_search(
            query=query,
            source="elibrary",
            limit=5
        )
        
        print(f"✓ Найдено статей: {len(results)}")
        
        if results:
            print("\nПример первой статьи:")
            first = results[0]
            print(f"  Название: {first.get('title', 'N/A')[:80]}...")
            print(f"  Авторы: {', '.join(first.get('authors', []))[:60]}...")
            print(f"  Год: {first.get('year', 'N/A')}")
            print(f"  URL статьи: {first.get('article_url', 'N/A')}")
            print(f"  PDF URL: {first.get('pdf_url', 'N/A')}")
            
            # Сохраняем результаты
            with open('test_elibrary_results.json', 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print("\n✓ Результаты сохранены в test_elibrary_results.json")
        else:
            print("⚠ Статьи не найдены")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Главная функция"""
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ РОССИЙСКИХ ИСТОЧНИКОВ")
    print("="*60)
    
    # Тест CyberLeninka
    await test_cyberleninka()
    
    # Небольшая пауза между тестами
    await asyncio.sleep(2)
    
    # Тест eLibrary
    await test_elibrary()
    
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())        
        if results:
            print("\nПример первой статьи:")
            first = results[0]
            print(f"  Название: {first.get('title', 'N/A')[:80]}...")
            print(f"  Авторы: {', '.join(first.get('authors', []))[:60]}...")
            print(f"  Год: {first.get('year', 'N/A')}")
            print(f"  URL статьи: {first.get('article_url', 'N/A')}")
            print(f"  PDF URL: {first.get('pdf_url', 'N/A')}")
            
            # Сохраняем результаты
            with open('test_elibrary_results.json', 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print("\n✓ Результаты сохранены в test_elibrary_results.json")
        else:
            print("⚠ Статьи не найдены")
            
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Главная функция"""
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ РОССИЙСКИХ ИСТОЧНИКОВ")
    print("="*60)
    
    # Тест CyberLeninka
    await test_cyberleninka()
    
    # Небольшая пауза между тестами
    await asyncio.sleep(2)
    
    # Тест eLibrary
    await test_elibrary()
    
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
