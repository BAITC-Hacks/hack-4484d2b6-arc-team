import pytest

from app.models import TaskCard
from app.scoring import calculate_rating, readiness_level


def test_empty_card_and_ai_suggestions_earn_no_points():
    rating = calculate_rating(TaskCard(title="Учёт товаров", ai_recommendations=["FastAPI", "SQLite"]))
    assert rating.score == 0
    assert rating.level == "draft"
    assert rating.missing_fields == ["context", "need", "data", "expected_result", "success_criteria",
                                     "constraints", "users", "contact", "interaction_format"]


def test_complete_card_has_case_weights_and_explainable_total():
    card = TaskCard(context="Остатки ведутся вручную", need="Автоматизировать учёт",
                    data="CSV на 500 товаров", expected_result="Прототип учёта товаров",
                    success_criteria="Найти все товары с остатком ниже 5 на тестовом CSV",
                    constraints="Две недели, без доступа к рабочей базе", users="Кладовщик",
                    contact="demo@example.test", interaction_format="Созвон по вторникам, отзыв в течение суток")
    rating = calculate_rating(card)
    assert rating.score == 100
    assert rating.level == "priority"
    assert rating.missing_fields == []
    assert [c.maximum for c in rating.categories] == [20, 20, 15, 15, 10, 10, 10]
    assert sum(c.points for c in rating.categories) == rating.score
    for category in rating.categories:
        assert category.points == sum(f.points for f in category.fields) == category.maximum


@pytest.mark.parametrize("field,points", [("context", 10), ("need", 10), ("data", 20),
    ("expected_result", 15), ("success_criteria", 15), ("constraints", 10), ("users", 10),
    ("contact", 4), ("interaction_format", 6)])
def test_individual_fields_and_text_length(field, points):
    short = calculate_rating(TaskCard(**{field: "Сведения бизнеса"}))
    long = calculate_rating(TaskCard(**{field: "Сведения бизнеса. " * 100}))
    assert short == long
    assert short.score == points
    assert field not in short.missing_fields


@pytest.mark.parametrize("placeholder", ["", "   ", "---", "???", "Не знаю!", "  TBD  ",
    "n/a", "Ｎ／Ａ", "Не указано", "Уточним потом", "белгісіз", "unknown"])
def test_placeholders_do_not_inflate_score(placeholder):
    rating = calculate_rating(TaskCard(data=placeholder))
    assert rating.score == 0
    assert "data" in rating.missing_fields


@pytest.mark.parametrize("score,level", [(0, "draft"), (39, "draft"), (40, "working"),
    (69, "working"), (70, "ready"), (89, "ready"), (90, "priority"), (100, "priority")])
def test_level_boundaries(score, level):
    assert readiness_level(score) == level


@pytest.mark.parametrize("score", [-1, 101])
def test_invalid_score_has_no_level(score):
    with pytest.raises(ValueError):
        readiness_level(score)
