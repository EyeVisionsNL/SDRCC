export function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const pages = document.querySelectorAll(".tab-page");
    const header = document.querySelector(".topbar");
    const bannerSceneByTab = {
        system: "system", radio: "radio", "radio-view": "traffic", "traffic-voice": "traffic", "hf-monitor": "radio",
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
            buttons.forEach(item => item.classList.remove("active"));
            pages.forEach(page => page.classList.remove("active"));
            button.classList.add("active");
            setBannerScene(tab);
            const page = document.getElementById(`tab-${tab}`);
            if (page) page.classList.add("active");
        });
    });
}
