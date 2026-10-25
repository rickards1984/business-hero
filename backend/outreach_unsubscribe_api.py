"""OUT-16: the public unsubscribe page for outreach emails.

GET shows a confirmation with a button and never changes anything (mail
scanners and link previews open links). POST unsubscribes: it is what the
button posts, and what Gmail, Yahoo and Apple Mail send for one-click
unsubscribe (RFC 8058: `List-Unsubscribe=One-Click`). Unauthenticated and
rate limited by IP alone (a public route: an unverified bearer token must not
buy a fresh bucket); an unknown or revoked token is a plain 404.
"""
import html

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from db import get_session
from rate_limiting import ip_key, limiter
from services import outreach_send
from services.aria_actions import ActionRefused

router = APIRouter(tags=["Public"])

PAGE = """<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{title}</title>
<style>body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f6f7f9;color:#101828;margin:0}}
main{{max-width:480px;margin:12vh auto;padding:28px;background:#fff;border:1px solid #e4e7ec;border-radius:16px}}
h1{{font-size:22px;margin:0 0 12px}}p{{line-height:1.5;color:#344054}}
button{{font:inherit;font-size:16px;font-weight:600;padding:12px 20px;border:0;border-radius:10px;background:#2f54eb;color:#fff;cursor:pointer}}</style>
</head><body><main>{body}</main></body></html>"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=html.escape(title), body=body), status_code=status,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _invalid() -> HTMLResponse:
    return _page("Link not valid", "<h1>This unsubscribe link isn't valid</h1>"
                 "<p>It may be incomplete or out of date. If you keep receiving emails you don't want, reply to one "
                 "of them asking to be removed and you will be.</p>", 404)


@router.get("/u/{token}", response_class=HTMLResponse)
@limiter.limit("60/minute", key_func=ip_key)
def confirm(request: Request, token: str, session: Session = Depends(get_session)):
    try:
        outreach_send.unsubscribe(session, token=token, method="GET")
    except ActionRefused:
        return _invalid()
    return _page("Unsubscribe", "<h1>Unsubscribe</h1><p>Stop receiving these emails? One click and you won't be "
                 "contacted again.</p><form method='post'><button type='submit'>Unsubscribe</button></form>")


@router.post("/u/{token}", response_class=HTMLResponse)
@limiter.limit("60/minute", key_func=ip_key)
def unsubscribe(request: Request, token: str, session: Session = Depends(get_session)):
    try:
        outreach_send.unsubscribe(session, token=token, method="POST")
    except ActionRefused:
        return _invalid()
    return _page("Unsubscribed", "<h1>You're unsubscribed</h1><p>You won't receive any more of these emails. "
                 "Sorry for the bother.</p>")
