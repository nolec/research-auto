from __future__ import annotations

from html import unescape
from html.parser import HTMLParser

from src.source_spike.raw_items import normalize_text


_BLOCKS = frozenset({"p", "div", "br", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"})
_SKIP = frozenset({"script", "style"})


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip_depth += 1
        elif not self.skip_depth and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.skip_depth and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [normalize_text(line) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def html_body_to_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    parser.close()
    return parser.text()


def html_title_to_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    parser.close()
    return normalize_text(unescape(parser.text()))
