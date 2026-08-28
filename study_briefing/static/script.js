const form = document.getElementById("study-form");
const error = document.getElementById("error");
const started = document.getElementById("started");
const button = document.getElementById("start-button");

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    error.hidden = true;
    button.disabled = true;

    try {
        const response = await fetch("/start-study", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({}), // Sending an empty payload
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Studie konnte nicht gestartet werden.");
        }

        form.hidden = true;
        started.hidden = false;

        // Tell the Playwright page that the participant clicked Start.
        window.dispatchEvent(
            new CustomEvent("study-started", {
                detail: data,
            })
        );
    } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        button.disabled = false;
    }
});
