from aishelf.site.markdown import render_markdown


def test_renders_basic_markdown():
    html = render_markdown("# Title\n\nsome **bold** text")
    assert "<h1>" in html and "Title" in html
    assert "<strong>bold</strong>" in html


def test_strips_script_tags():
    html = render_markdown("hi\n\n<script>alert(1)</script>")
    assert "<script" not in html
    assert "alert(1)" not in html


def test_strips_inline_event_handlers_and_js_urls():
    html = render_markdown('<a href="javascript:alert(1)" onclick="x()">click</a>')
    assert "javascript:" not in html
    assert "onclick" not in html


def test_empty_input_returns_empty_string():
    assert render_markdown("") == ""


def test_renderer_failure_falls_back_to_escaped_text(monkeypatch):
    import aishelf.site.markdown as m

    def boom(_text):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(m, "_render", boom)
    html = render_markdown("<b>raw</b> & stuff")
    # falls back to escaped plain text, never raises
    assert "&lt;b&gt;" in html and "&amp;" in html
