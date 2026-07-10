export function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const pages = document.querySelectorAll(".tab-page");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const tab = button.dataset.tab;

            buttons.forEach(item => item.classList.remove("active"));
            pages.forEach(page => page.classList.remove("active"));

            button.classList.add("active");

            const page = document.getElementById(`tab-${tab}`);
            if (page) page.classList.add("active");
        });
    });
}
