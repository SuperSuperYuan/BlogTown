from aishelf.db.tokenize import bigrams, to_match_query, to_match_query_or


def test_bigrams_cjk_multichar():
    assert bigrams("大语言模型") == "大语 语言 言模 模型"


def test_bigrams_cjk_two_char():
    assert bigrams("检索") == "检索"


def test_bigrams_single_cjk_char():
    assert bigrams("中") == "中"


def test_bigrams_ascii_lowercased_and_whole():
    assert bigrams("RAG Transformer") == "rag transformer"


def test_bigrams_mixed():
    assert bigrams("RAG 检索增强") == "rag 检索 索增 增强"


def test_bigrams_strips_punctuation_and_empty():
    assert bigrams("！！！") == ""
    assert bigrams("") == ""


def test_to_match_query_two_char():
    assert to_match_query("检索") == '"检索"'


def test_to_match_query_multichar_is_anded():
    assert to_match_query("大模型") == '"大模" AND "模型"'


def test_to_match_query_empty_when_no_tokens():
    assert to_match_query("   ") == ""
    assert to_match_query("！") == ""


# --- to_match_query_or ---

def test_to_match_query_or_multichar_is_ored():
    result = to_match_query_or("大模型")
    assert result == '"大模" OR "模型"'
    assert " OR " in result
    assert " AND " not in result


def test_to_match_query_or_bigrams_are_quoted():
    result = to_match_query_or("检索增强")
    # each bigram should be wrapped in double quotes
    for bigram in ["检索", "索增", "增强"]:
        assert f'"{bigram}"' in result
    assert " OR " in result
    assert " AND " not in result


def test_to_match_query_or_two_char_cjk():
    # a two-char CJK string produces exactly one bigram — no OR needed but still quoted
    result = to_match_query_or("检索")
    assert result == '"检索"'


def test_to_match_query_or_empty_when_no_tokens():
    assert to_match_query_or("") == ""
    assert to_match_query_or("   ") == ""
    assert to_match_query_or("！！") == ""


def test_to_match_query_or_ascii_consistent_with_and():
    # for a single ASCII term both modes produce the same quoted token
    assert to_match_query_or("rag") == to_match_query("rag")
