"""Regression test for the draft-format double-encoding bug.

Bug (introduced by c5c4d43 "AI-generated drafts: real signature", fixed here):
when a user's signature is HTML, draft_generate's append_signature_to_body already
returns HTML, but draft_save then ran the result through _plain_to_html() which
html.escape()'d the tags into literal <p> / &#x27; / &amp; garbage in Outlook —
exactly what a client (Daniel) reported. Plain/empty-signature users were unaffected,
which is why it looked account-specific.

Fix: draft_save passes the body straight to create_draft's _ensure_html — the SINGLE,
idempotent HTML-conversion point. These tests lock that the assembled draft body is
clean HTML and never double-escaped, mirroring that fixed pipeline.
"""
from src.modules.profile import append_signature_to_body
from src.graph import _ensure_html


def _assemble(body: str, signature: str) -> str:
    # Mirrors the FIXED pipeline exactly: append signature upstream, then the
    # single conversion point (create_draft's _ensure_html). No _plain_to_html.
    return _ensure_html(append_signature_to_body(body, signature))


def test_html_signature_is_not_double_escaped():
    body = "Just circling back. I'm still looking forward to the JSON output."
    sig = "Daniel Bin Zhang<br>Hunter Ai &amp; IPS Consultancy<br>+12368681898"
    out = _assemble(body, sig)
    # Tags must stay real, never escaped into literals.
    assert "&lt;p&gt;" not in out
    assert "&lt;br&gt;" not in out
    # Apostrophe must be single-escaped, never double (&amp;#x27; / &amp;#39;).
    assert "&amp;#x27;" not in out
    assert "&amp;#39;" not in out
    # The signature's existing &amp; entity must stay single, not become &amp;amp;.
    assert "&amp;amp;" not in out
    # Real HTML structure is present.
    assert "<p>" in out
    assert "<br>" in out


def test_plain_signature_still_makes_paragraphs():
    out = _assemble("Line one.\n\nLine two.", "Best,\nJason")
    assert "<p>" in out
    assert "&lt;" not in out  # nothing was escaped into a literal tag


def test_no_signature_plain_body():
    out = _assemble("Hello there.", "")
    assert out == "<p>Hello there.</p>"
