"""Проверка цитаты: есть ли её последовательность слов в тексте фрагмента.

Сравнение по словам без учёта регистра, пунктуации и markdown: лишняя точка не даёт ложного
отказа, а искажённая или чужая цитата не проходит.
"""

import re

_WORD = re.compile(r"\w+")


def words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(text.casefold()))


def quote_in(text: str, quote: str) -> bool:
    needle = words(quote)
    haystack = words(text)
    size = len(needle)
    return bool(needle) and any(
        haystack[i : i + size] == needle for i in range(len(haystack) - size + 1)
    )
