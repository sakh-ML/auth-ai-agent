const form = document.getElementById("study-form");
const error = document.getElementById("error");
const started = document.getElementById("started");
const button = document.getElementById("start-button");

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    error.hidden = true;
    button.disabled = true;

    const participantId = Number(
        document.getElementById("participant-id").value
    );
    const modeValue = document.getElementById("mode").value;
    const mode = modeValue === "" ? null : modeValue;

    try {
        const response = await fetch("/start-study", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                participant_id: participantId,
                mode: mode,
            }),
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
