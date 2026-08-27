"""
Provides custom, in-page UI overlays for participant interaction.

Injects JavaScript-based dialogs and event listeners directly into the
DOM via Playwright. This bypasses the limitations of native browser dialogs
in automated sessions, providing a user-friendly interface for asking
permission (Mode B) and listening for manual Escape interruptions (Mode C1).
"""

from __future__ import annotations
import asyncio
import uuid

_DIALOG_JS = """
(payload) => {
    const { question, fnName } = payload;
    let el = document.getElementById('__agent_dialog__');
    if (el) el.remove();

    el = document.createElement('div');
    el.id = '__agent_dialog__';
    el.style.position = 'fixed';
    el.style.top = '16px';
    el.style.right = '16px';
    el.style.zIndex = '2147483647';
    el.style.background = '#1f2937';
    el.style.color = '#fff';
    el.style.padding = '16px 20px';
    el.style.borderRadius = '10px';
    el.style.fontFamily = 'sans-serif';
    el.style.fontSize = '14px';
    el.style.boxShadow = '0 4px 16px rgba(0,0,0,0.3)';
    el.style.maxWidth = '320px';

    const text = document.createElement('div');
    text.textContent = question;
    text.style.marginBottom = '12px';
    el.appendChild(text);

    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.gap = '8px';

    const yes = document.createElement('button');
    yes.textContent = 'Ja';
    yes.style.padding = '6px 14px';
    yes.style.cursor = 'pointer';
    yes.style.border = 'none';
    yes.style.borderRadius = '6px';
    yes.onclick = () => { window[fnName](true); };

    const no = document.createElement('button');
    no.textContent = 'Nein';
    no.style.padding = '6px 14px';
    no.style.cursor = 'pointer';
    no.style.border = 'none';
    no.style.borderRadius = '6px';
    no.onclick = () => { window[fnName](false); };

    row.appendChild(yes);
    row.appendChild(no);
    el.appendChild(row);
    document.body.appendChild(el);
}
"""

_ESCAPE_JS = """
(fnName) => {
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { window[fnName](); }
    });
}
"""


async def ask_user_yes_no(page, question: str) -> bool:
    """Mode B popup. Shows a Ja/Nein overlay and waits for the participant
    to click one of the buttons."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    fn_name = f"__agent_answer_{uuid.uuid4().hex}__"

    async def _on_answer(answer: bool):
        if not future.done():
            future.set_result(answer)

    await page.expose_function(fn_name, _on_answer)
    await page.evaluate(_DIALOG_JS, {"question": question, "fnName": fn_name})

    try:
        result = await future
    finally:
        try:
            await page.evaluate(
                "() => { const el = document.getElementById('__agent_dialog__'); "
                "if (el) el.remove(); }"
            )
        except Exception:
            pass
    return result


async def watch_for_escape(page) -> asyncio.Event:
    """Mode C1 interrupt. Injects an Escape-key listener and returns an
    asyncio.Event that gets set the moment the participant presses it."""
    event = asyncio.Event()
    fn_name = f"__agent_escape_{uuid.uuid4().hex}__"

    async def _on_escape():
        event.set()

    await page.expose_function(fn_name, _on_escape)
    await page.evaluate(_ESCAPE_JS, fn_name)
    return event
