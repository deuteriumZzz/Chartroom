from chartroom.knowledge.domain.sparse import bm25_vector, term_id


def _weights(text: str) -> dict[int, float]:
    vector = bm25_vector(text)
    return dict(zip(vector.indices, vector.values, strict=True))


def test_terms_are_lowercased_and_counted_once_per_index() -> None:
    weights = _weights("Fire FIRE fire alarm")
    assert set(weights) == {term_id("fire"), term_id("alarm")}
    assert weights[term_id("fire")] > weights[term_id("alarm")]


def test_term_frequency_saturates() -> None:
    once = _weights("pump " + "x " * 9)[term_id("pump")]
    ten_times = _weights("pump " * 10)[term_id("pump")]
    assert ten_times < 10 * once  # насыщение: 10 повторов не дают 10-кратного веса


def test_longer_text_lowers_weight_of_a_single_mention() -> None:
    short = _weights("valve closed")[term_id("valve")]
    long = _weights("valve " + "word " * 200)[term_id("valve")]
    assert long < short


def test_vector_is_deterministic_sorted_and_handles_cyrillic() -> None:
    vector = bm25_vector("Пожар в МО, пожар!")
    assert vector == bm25_vector("Пожар в МО, пожар!")
    assert list(vector.indices) == sorted(vector.indices)
    assert term_id("пожар") in vector.indices
    assert bm25_vector("  ...  ").indices == ()
