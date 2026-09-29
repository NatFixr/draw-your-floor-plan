import pytest

from floorplan.i18n import t
from floorplan.units import fmt_area_ft2, fmt_area_m2, fmt_ftin, fmt_m, parse_length


@pytest.mark.parametrize("src,expected", [
    (66, 66.0), (66.5, 66.5), ("66", 66.0), ("66.5", 66.5),
    ("5'6\"", 66.0), ("5' 6\"", 66.0), ("5'-6 1/2\"", 66.5), ("5'", 60.0), ("6\"", 6.0),
    ("66 1/2", 66.5), ("1/2\"", 0.5),
    ("167.6cm", 167.6 / 2.54), ("167,6 cm", 167.6 / 2.54), ("1676mm", 1676 / 25.4),
    ("2.1m", 2.1 / 0.0254), ("2,10 m", 2.1 / 0.0254), ("2.54 CM", 1.0),
])
def test_parse_length(src, expected):
    assert parse_length(src) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "abc", "5'6'", "1/0\"", "2 x 4", None, True, "m"])
def test_parse_length_rejects(bad):
    with pytest.raises(ValueError):
        parse_length(bad)


@pytest.mark.parametrize("inches,expected", [
    (0.5, "0'-0 1/2\""), (66, "5'-6\""), (144, "12'-0\""), (8, "0'-8\""),
    (66.5, "5'-6 1/2\""), (11.9, "1'-0\""), (0.25, "0'-0 1/4\""), (0.75, "0'-0 3/4\""),
])
def test_fmt_ftin(inches, expected):
    assert fmt_ftin(inches) == expected


def test_fmt_m_and_areas():
    assert fmt_m(66, "fr") == "1,68"
    assert fmt_m(66, "en") == "1.68"
    assert fmt_m(66, "bi") == "1.68"
    assert fmt_m(66, "fr", nd=1) == "1,7"
    assert fmt_area_m2(33000, "fr") == "21,3"
    assert fmt_area_m2(33000, "en") == "21.3"
    assert fmt_area_ft2(33000) == "229"


def test_i18n():
    assert t("to_confirm", "fr") == "à confirmer"
    assert t("to_confirm", "en") == "to confirm"
    assert t("to_confirm", "bi") == "à confirmer"
    assert t("no_such_key", "fr") == "no_such_key"
