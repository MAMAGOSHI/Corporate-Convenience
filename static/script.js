document.addEventListener("DOMContentLoaded", function () {
    const button = document.getElementById("draft-response");
    if (!button) return;

    button.addEventListener("click", async function () {
        const status = document.getElementById("draft-status");
        const body = document.getElementById("body");
        const marker = document.getElementById("is-ai-assisted");
        const token = document.querySelector('meta[name="csrf-token"]')?.content;

        button.disabled = true;
        button.textContent = "Preparing draft...";
        status.textContent = "Creating a suggested response. Please wait.";

        try {
            const response = await fetch(button.dataset.url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": token || ""
                },
                body: JSON.stringify({})
            });

            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Draft generation failed.");

            body.value = result.draft;
            marker.value = result.source === "Gemini AI" ? "true" : "false";
            status.textContent = result.notice || (result.source + " generated. Review and edit it before sending.");
        } catch (error) {
            status.textContent = error.message;
        } finally {
            button.disabled = false;
            button.textContent = "Generate draft ✦";
        }
    });
});
