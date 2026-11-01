const searchInput = document.querySelector("#medicine-search");
const medicineRows = [...document.querySelectorAll("#medicine-rows tr[data-search]")];
const noResults = document.querySelector("#no-results");

searchInput?.addEventListener("input", () => {
  const query = searchInput.value.trim().toLocaleLowerCase("sk");
  let visibleCount = 0;
  for (const row of medicineRows) {
    const matches = row.dataset.search.toLocaleLowerCase("sk").includes(query);
    row.hidden = !matches;
    visibleCount += Number(matches);
  }
  noResults.hidden = visibleCount > 0;
});