"""MVP completeness rubric; never relies on AI, popularity, or text length."""
import re
import unicodedata

from app.models import Rating, RatingCategory, RatingField, ReadinessLevel, TaskCard

# Stable category keys and field labels are also the UI explanation.
RULES = (
    ("context_need", "Контекст и потребность", (("context", "Текущий процесс", 10), ("need", "Необходимое изменение", 10))),
    ("data", "Данные и материалы", (("data", "Доступные данные, материалы или источники", 20),)),
    ("expected_result", "Ожидаемый результат", (("expected_result", "Результат работы команды", 15),)),
    ("success_criteria", "Критерии успеха", (("success_criteria", "Критерии и способ проверки", 15),)),
    ("constraints", "Ограничения", (("constraints", "Сроки, технологии или доступы", 10),)),
    ("users", "Пользователи", (("users", "Целевые пользователи", 10),)),
    ("business_contact", "Связь с бизнесом", (("contact", "Контакт", 4), ("interaction_format", "Консультации и обратная связь", 6))),
)
PLACEHOLDERS = {
    "не знаю", "неизвестно", "пока неизвестно", "не определено", "не указано",
    "уточним", "уточним потом", "уточняется", "позже", "заполним позже",
    "нет информации", "нет ответа", "без ответа", "заглушка", "тест", "test",
    "tbd", "todo", "n a", "na", "none", "null", "unknown", "i don t know",
    "not specified", "not sure", "to be determined", "белгісіз", "білмеймін",
}


def is_filled(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))
    return bool(normalized) and normalized not in PLACEHOLDERS


def readiness_level(score: int) -> ReadinessLevel:
    if not 0 <= score <= 100:
        raise ValueError("Score must be between 0 and 100")
    if score < 40:
        return ReadinessLevel.DRAFT
    if score < 70:
        return ReadinessLevel.WORKING
    if score < 90:
        return ReadinessLevel.READY
    return ReadinessLevel.PRIORITY


def calculate_rating(card: TaskCard) -> Rating:
    categories = []
    missing_fields = []
    for key, label, rules in RULES:
        fields = []
        for name, field_label, weight in rules:
            filled = is_filled(getattr(card, name))
            fields.append(RatingField(field=name, label=field_label, points=weight if filled else 0, maximum=weight))
            if not filled:
                missing_fields.append(name)
        categories.append(RatingCategory(key=key, label=label, points=sum(f.points for f in fields),
                                         maximum=sum(f.maximum for f in fields), fields=fields))
    score = sum(category.points for category in categories)
    return Rating(score=score, level=readiness_level(score), categories=categories, missing_fields=missing_fields)
