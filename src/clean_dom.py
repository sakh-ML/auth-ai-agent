"""
Utility for extracting and sanitizing the HTML DOM for LLM processing.

Provides functionality to clone and clean the active webpage's DOM by
stripping out token-heavy, non-interactive noise.
"""


async def get_page_dom(page) -> str:
    """
    Extracts a cleaned, token-efficient version of the DOM.
    Strips scripts, SVGs, styles, and hidden data while keeping
    IDs, names, classes, and form elements intact for the LLM.
    """
    clean_html = await page.evaluate(
        """() => {
        // 1. Clone the body so we don't modify the actual live webpage
        const clone = document.body.cloneNode(true);

        // 2. Define tags that provide zero value to an AI agent trying to log in
        const tagsToRemove = [
            'script', 'style', 'svg', 'canvas', 'noscript',
            'iframe', 'meta', 'link', 'path', 'symbol', 'defs'
        ];

        // 3. Remove all those noise tags
        tagsToRemove.forEach(tag => {
            const elements = clone.querySelectorAll(tag);
            elements.forEach(el => el.remove());
        });

        // 4. Clean up massive attributes (like inline styles and base64 images)
        const allElements = clone.querySelectorAll('*');
        allElements.forEach(el => {
            // Remove inline styles (massive token waste)
            el.removeAttribute('style');

            // Remove Base64 Image data but keep the image tag so AI knows it's there
            if (el.tagName.toLowerCase() === 'img') {
                const src = el.getAttribute('src');
                if (src && src.startsWith('data:image')) {
                    el.setAttribute('src', 'BASE64_IMAGE_REMOVED');
                }
            }

            // Optional: Remove SVGs that are inline in weird ways
            if (el.tagName.toLowerCase() === 'g' || el.tagName.toLowerCase() === 'rect') {
                el.remove();
            }
        });

        // 5. Remove HTML comments (<!-- -->) as they are useless for interaction
        const iterator = document.createNodeIterator(clone, NodeFilter.SHOW_COMMENT, null, false);
        let curNode;
        const comments = [];
        while (curNode = iterator.nextNode()) {
            comments.push(curNode);
        }
        comments.forEach(c => c.remove());

        // 6. Return the compressed, clean HTML
        return clone.innerHTML;
    }"""
    )

    return clean_html
