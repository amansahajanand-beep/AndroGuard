"""Get the text of a privacy policy from a URL or an uploaded file.

The URL comes from a user, and the server fetches it, so the fetch is restricted: http(s)
only, every address the host resolves to must be public (no loopback, private, link-local
or metadata ranges), redirects are followed manually and re-checked at each hop, and the
size and time are capped. Returns ``(text, error)``; never raises.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 12
_TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "text/markdown")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[override]
        return None


class _TextOnly(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in self._SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextOnly()
    try:
        parser.feed(markup)
    except Exception:  # noqa: BLE001 - malformed HTML still yields whatever text was parsed
        pass
    return normalize_text("".join(parser.parts))


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_policy_text(url: str) -> tuple[str | None, str | None]:
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(current)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None, "The privacy policy link must be an http(s) URL."
        if not _host_is_public(parsed.hostname):
            return None, "The privacy policy host is not a public address."
        request = urllib.request.Request(current, headers={"User-Agent": "AndroGuard-PolicyReader/1.0", "Accept": "text/html,text/plain,application/pdf"})
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                body = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                current = urllib.parse.urljoin(current, exc.headers["Location"])
                continue
            return None, f"The privacy policy URL returned HTTP {exc.code}."
        except Exception as exc:  # noqa: BLE001
            logger.info("[POLICY] fetch failed: %s", type(exc).__name__)
            return None, "The privacy policy URL could not be fetched."
        if len(body) > MAX_BYTES:
            return None, "The privacy policy is too large to read."
        if "pdf" in content_type or body[:5] == b"%PDF-":
            return extract_policy_text("policy.pdf", body)
        if not any(t in content_type for t in _TEXT_TYPES) and content_type:
            return None, f"Unsupported privacy policy content type ({content_type.split(';')[0]})."
        text = _decode(body, content_type)
        if "html" in content_type or re.search(r"<html|<body|<p[ >]", text[:2000], re.I):
            text = html_to_text(text)
        else:
            text = normalize_text(text)
        return (text, None) if len(text) >= 200 else (None, "The privacy policy page has too little readable text (it may need JavaScript).")
    return None, "The privacy policy URL redirected too many times."


def extract_policy_text(filename: str, data: bytes) -> tuple[str | None, str | None]:
    """Text from an uploaded policy: .txt/.md/.html, .pdf (pypdf) or .docx."""
    name = (filename or "").lower()
    try:
        if name.endswith((".txt", ".md", ".text")):
            return _ok(normalize_text(data.decode("utf-8", errors="replace")))
        if name.endswith((".html", ".htm")):
            return _ok(html_to_text(data.decode("utf-8", errors="replace")))
        if name.endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return _ok(normalize_text(re.sub(r"<[^>]+>", "", xml)))
        if name.endswith(".pdf"):
            try:
                from pypdf import PdfReader
            except ImportError:
                return None, "PDF policies need the pypdf package on the server."
            reader = PdfReader(io.BytesIO(data))
            return _ok(normalize_text("\n".join((page.extract_text() or "") for page in reader.pages[:60])))
    except Exception as exc:  # noqa: BLE001
        logger.info("[POLICY] could not read %s: %s", name, type(exc).__name__)
        return None, "The privacy policy file could not be read."
    return None, "Unsupported privacy policy file type (use .pdf, .docx, .txt or .html)."


def _ok(text: str) -> tuple[str | None, str | None]:
    return (text, None) if len(text) >= 200 else (None, "The privacy policy has too little readable text.")
