export function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const pages = document.querySelectorAll(".tab-page");
    const header = document.querySelector(".topbar");
    const bannerSceneByTab = {
        system: "system", radio: "radio", "radio-view": "radio", "traffic-voice": "traffic", "hf-monitor": "receiver",
        mission: "satellite", "mission-planner": "satellite", images: "satellite", history: "satellite",
        "mission-analytics": "satellite", logs: "logs",
    };
    function setBannerScene(tab) {
        if (header) header.dataset.bannerScene = bannerSceneByTab[tab] || "system";
    }
    const initialTab = document.querySelector(".tab-button.active");
    if (initialTab) setBannerScene(initialTab.dataset.tab);
    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const tab = button.dataset.tab;
            const previousTab = document.querySelector(".tab-button.active")?.dataset.tab;
            const page = document.getElementById(`tab-${tab}`);
            if (!page || previousTab === tab) return;
            buttons.forEach(item => item.classList.remove("active"));
            pages.forEach(item => item.classList.remove("active"));
            button.classList.add("active");
            setBannerScene(tab);
            page.classList.add("active");
            // Only user-initiated, genuine tab switches produce the blip event.
            window.dispatchEvent(new CustomEvent("sdrcc:tab-changed", {
                detail: { tab, previousTab }
            }));
        });
    });
}
