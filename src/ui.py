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
    
    // Center the popup on the screen so it's impossible to miss
    el.style.position = 'fixed';
    el.style.top = '50%';
    el.style.left = '50%';
    el.style.transform = 'translate(-50%, -50%)';
    el.style.zIndex = '2147483647';
    
    // Classy, modern design - Compact Version
    el.style.background = '#ffffff';
    el.style.color = '#111827';
    el.style.padding = '24px'; 
    el.style.borderRadius = '12px';
    el.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    el.style.textAlign = 'center';
    el.style.maxWidth = '320px'; 
    el.style.width = '90%';
    
    // The "backdrop hack": this dims the rest of the screen behind the popup
    el.style.boxShadow = '0 10px 25px rgba(0,0,0,0.1), 0 0 0 9999px rgba(0,0,0,0.4)';

    // Smooth, professional fade-in
    el.animate([
        { opacity: 0, transform: 'translate(-50%, -48%)' },
        { opacity: 1, transform: 'translate(-50%, -50%)' }
    ], { duration: 300, easing: 'ease-out' });

    const text = document.createElement('div');
    text.textContent = question;

    text.style.whiteSpace = 'pre-wrap';

    text.style.fontSize = '15px'; 
    text.style.fontWeight = '500';
    text.style.lineHeight = '1.4';
    text.style.marginBottom = '20px'; 
    el.appendChild(text);

    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.justifyContent = 'center';
    row.style.gap = '10px';

    // Primary Button (Yes)
    const yes = document.createElement('button');
    yes.textContent = 'Ja';
    yes.style.padding = '8px 20px'; 
    yes.style.fontSize = '14px';
    yes.style.fontWeight = '600';
    yes.style.cursor = 'pointer';
    yes.style.border = '1px solid #111827';
    yes.style.background = '#111827';
    yes.style.color = '#ffffff';
    yes.style.borderRadius = '8px';
    yes.style.transition = 'background 0.2s';
    yes.onmouseover = () => yes.style.background = '#374151';
    yes.onmouseout = () => yes.style.background = '#111827';
    yes.onclick = () => { window[fnName](true); };

    // Secondary Button (No)
    const no = document.createElement('button');
    no.textContent = 'Nein';
    no.style.padding = '8px 20px'; 
    no.style.fontSize = '14px';
    no.style.fontWeight = '600';
    no.style.cursor = 'pointer';
    no.style.border = '1px solid #d1d5db';
    no.style.background = '#ffffff';
    no.style.color = '#374151';
    no.style.borderRadius = '8px';
    no.style.transition = 'background 0.2s';
    no.onmouseover = () => no.style.background = '#f3f4f6';
    no.onmouseout = () => no.style.background = '#ffffff';
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
