"""Язык текста: русский или английский. Общий для ответов и агента."""

from enum import StrEnum

# Доля кириллицы, начиная с которой текст считается русским: «Что такое ECDIS MOB?» — русский.
_RUSSIAN_SHARE = 0.3


class Language(StrEnum):
    RU = "ru"
    EN = "en"


def detect_language(text: str) -> Language:
    letters = [c for c in text if c.isalpha()]
    cyrillic = sum("\u0400" <= c <= "\u04ff" for c in letters)
    return Language.RU if letters and cyrillic / len(letters) >= _RUSSIAN_SHARE else Language.EN
