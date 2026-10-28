import pytest

from atarilauncher import vdf


def test_nested_and_case_insensitive_keys():
    d = vdf.loads('"AppState" { "AppID" "620" "UserConfig" { "language" "english" } }')
    assert d["appstate"]["appid"] == "620"
    assert d["appstate"]["userconfig"]["language"] == "english"


def test_escapes_comments_and_unquoted():
    d = vdf.loads('// comment\n"a" { "name" "Portal \\"Test\\" \\\\ x" // trailing\n bare value }')
    assert d["a"]["name"] == 'Portal "Test" \\ x'
    assert d["a"]["bare"] == "value"


def test_bom_and_empty():
    assert vdf.loads("\ufeff") == {}
    assert vdf.loads('\ufeff"x" { }') == {"x": {}}


@pytest.mark.parametrize("bad", ['"a" {', '"a"', '}', '"a" { "b" }', '"unterminated'])
def test_errors(bad):
    with pytest.raises(vdf.VDFError):
        vdf.loads(bad)
