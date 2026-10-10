(() => {
  for (const input of document.querySelectorAll('[data-location-suggest="true"]')) {
    const list = input.list;
    const status = document.getElementById(input.getAttribute("aria-describedby"));
    if (!list || !status) continue;

    let timer;
    let controller;
    input.addEventListener("input", () => {
      window.clearTimeout(timer);
      if (controller) controller.abort();
      const query = input.value.trim();
      if (query.length < 2) {
        status.textContent = "";
        return;
      }
      timer = window.setTimeout(async () => {
        controller = new AbortController();
        try {
          const response = await fetch(`/api/locations?q=${encodeURIComponent(query)}`, {
            signal: controller.signal,
            headers: { Accept: "application/json" },
          });
          if (!response.ok) return;
          const suggestions = await response.json();
          list.replaceChildren();
          for (const place of suggestions) {
            const option = document.createElement("option");
            option.value = place.canonical_name;
            option.label = `${place.name} · ${place.target_type}`;
            list.append(option);
          }
          status.textContent = suggestions.length
            ? `${suggestions.length} matching Indian locations`
            : "No exact location suggestion; your typed place will still be searched.";
        } catch (error) {
          if (error.name !== "AbortError") status.textContent = "Location suggestions unavailable.";
        }
      }, 220);
    });
  }
})();
