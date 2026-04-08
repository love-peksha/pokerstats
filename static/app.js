const state = {
  selectedBuyIns: new Set(),
  selectedMultipliers: new Set(),
  selectedWeekdays: new Set(),
  selectedTimeSlots: new Set(),
  prizePoolMin: "",
  prizePoolMax: "",
  startedAtFrom: "",
  startedAtTo: "",
  filters: {
    buy_ins_cents: [],
    multipliers: [],
    weekdays: [],
    time_slots: [],
    prize_pools_cents: [],
    started_at_min: null,
    started_at_max: null,
  },
};

const WEEKDAY_META = [
  { value: 1, shortLabel: "Пн", fullLabel: "Понедельник" },
  { value: 2, shortLabel: "Вт", fullLabel: "Вторник" },
  { value: 3, shortLabel: "Ср", fullLabel: "Среда" },
  { value: 4, shortLabel: "Чт", fullLabel: "Четверг" },
  { value: 5, shortLabel: "Пт", fullLabel: "Пятница" },
  { value: 6, shortLabel: "Сб", fullLabel: "Суббота" },
  { value: 7, shortLabel: "Вс", fullLabel: "Воскресенье" },
];

const TIME_SLOT_META = [
  { value: "night", label: "Ночь" },
  { value: "morning", label: "Утро" },
  { value: "day", label: "День" },
  { value: "evening", label: "Вечер" },
];

const weekdayMetaByValue = new Map(WEEKDAY_META.map((item) => [item.value, item]));
const timeSlotMetaByValue = new Map(TIME_SLOT_META.map((item) => [item.value, item]));
const timeSlotOrder = new Map(TIME_SLOT_META.map((item, index) => [item.value, index]));

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

function centsToCurrency(cents) {
  return currencyFormatter.format((cents || 0) / 100);
}

function formatDelta(delta) {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(2)} п.п.`;
}

function comparisonClass(delta) {
  if (delta === null || delta === undefined) {
    return "is-neutral";
  }
  if (delta > 0.01) {
    return "is-above";
  }
  if (delta < -0.01) {
    return "is-below";
  }
  return "is-neutral";
}

function benchmarkPosition(percentage) {
  return Math.min(percentage, 99.5);
}

function scaledPosition(value, scaleMax) {
  if (!scaleMax || scaleMax <= 0) {
    return 0;
  }
  return (value / scaleMax) * 100;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toDateTimeLocalValue(value) {
  if (!value) {
    return "";
  }
  return value.replace(" ", "T").slice(0, 16);
}

function buildQueryString() {
  const params = new URLSearchParams();
  [...state.selectedBuyIns]
    .sort((left, right) => left - right)
    .forEach((value) => params.append("buy_in", (value / 100).toString()));
  [...state.selectedMultipliers]
    .sort((left, right) => left - right)
    .forEach((value) => params.append("multiplier", value.toString()));
  [...state.selectedWeekdays]
    .sort((left, right) => left - right)
    .forEach((value) => params.append("weekday", value.toString()));
  [...state.selectedTimeSlots]
    .sort((left, right) => (timeSlotOrder.get(left) ?? 0) - (timeSlotOrder.get(right) ?? 0))
    .forEach((value) => params.append("time_slot", value));

  if (state.prizePoolMin !== "") {
    params.set("prize_pool_min", state.prizePoolMin);
  }
  if (state.prizePoolMax !== "") {
    params.set("prize_pool_max", state.prizePoolMax);
  }
  if (state.startedAtFrom !== "") {
    params.set("started_at_from", state.startedAtFrom);
  }
  if (state.startedAtTo !== "") {
    params.set("started_at_to", state.startedAtTo);
  }

  const query = params.toString();
  return query ? `?${query}` : "";
}

async function fetchDashboard() {
  const response = await fetch(`/api/dashboard${buildQueryString()}`);
  if (!response.ok) {
    throw new Error("Не удалось загрузить статистику.");
  }
  return response.json();
}

function renderSummary(summary) {
  const items = [
    {
      label: "Турниров",
      value: summary.total_tournaments,
      note: "По текущему набору фильтров",
      tone: "is-primary",
    },
    {
      label: "Побед",
      value: `${summary.wins} (${summary.win_rate}%)`,
      note: "Первое место",
      tone: "is-accent",
    },
    {
      label: "Топ-2",
      value: `${summary.top_two} (${summary.top_two_rate}%)`,
      note: "Первое или второе место",
      tone: "is-accent",
    },
    {
      label: "Среднее место",
      value: summary.average_place.toFixed(2),
      note: "Чем меньше, тем лучше",
      tone: "is-soft",
    },
    {
      label: "ITM",
      value: `${summary.in_the_money} (${summary.in_the_money_rate}%)`,
      note: "Турниры с любым призом",
      tone: "is-soft",
    },
    {
      label: "Сумма бай-инов",
      value: centsToCurrency(summary.total_buy_ins_cents),
      note: "Общая сумма входов по текущему фильтру",
      tone: "is-soft",
    },
    {
      label: "Средняя доля призпула",
      value: `${summary.average_prize_pool_share_pct.toFixed(2)}%`,
      note: "Какой % от призового фонда вы забираете в среднем",
      tone: "is-soft",
    },
    {
      label: "Чистый результат",
      value: centsToCurrency(summary.net_profit_cents),
      note: "Выплаты минус бай-ины",
      tone: "is-profit",
    },
    {
      label: "ROI",
      value: `${summary.roi_pct.toFixed(2)}%`,
      note: `Чистый результат / сумма бай-инов: ${centsToCurrency(summary.total_buy_ins_cents)}`,
      tone: "is-profit",
    },
  ];

  items.splice(6, 0, {
    label: "\u0424\u0430\u043a\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0440\u0435\u0439\u043a",
    value: `${summary.actual_rake_pct.toFixed(2)}%`,
    note: `\u0421\u043e\u0431\u0440\u0430\u043d\u043e ${centsToCurrency(summary.total_entry_buy_ins_cents)}, \u0432\u044b\u043f\u043b\u0430\u0447\u0435\u043d\u043e ${centsToCurrency(summary.total_prize_pools_cents)}`,
    tone: "is-soft",
  });

  document.getElementById("summary-grid").innerHTML = items
    .map(
      (item) => `
        <article class="summary-card ${item.tone}">
          <p class="summary-label">${escapeHtml(item.label)}</p>
          <h3 class="summary-value">${escapeHtml(item.value)}</h3>
          <p class="summary-note">${escapeHtml(item.note)}</p>
        </article>
      `
    )
    .join("");
}

function renderDistribution(distribution, totalTournaments) {
  const container = document.getElementById("distribution-table");
  const caption = document.getElementById("distribution-caption");
  const maxPercentage = distribution.length
    ? Math.max(...distribution.map((row) => row.percentage), 0)
    : 0;
  caption.textContent = totalTournaments
    ? `Показано ${totalTournaments} турниров по текущим фильтрам. Полосы масштабируются от текущего максимума, отметка на шкале = 1/6, то есть 16.67%.`
    : "Нет турниров для отображения";

  if (!distribution.length) {
    container.innerHTML = document.getElementById("empty-state-template").innerHTML;
    return;
  }

  container.innerHTML = `
    <div class="table-scroll table-scroll-distribution">
      <div class="distribution-table-inner">
        <div class="distribution-head">
          <span>Место</span>
          <span>Частота</span>
          <span>Факт / к 1/6</span>
        </div>
        ${distribution
          .map(
            (row) => `
              <div class="distribution-row ${comparisonClass(row.delta_percentage_points)}">
                <strong>${row.place}</strong>
                <div class="bar-cell">
                  <div class="bar-track">
                    <div class="bar-benchmark" style="left: ${benchmarkPosition(scaledPosition(row.expected_percentage, maxPercentage))}%"></div>
                    <div class="bar-fill ${comparisonClass(row.delta_percentage_points)}" style="width: ${Math.max(scaledPosition(row.percentage, maxPercentage), 3)}%"></div>
                  </div>
                  <span>${row.count}</span>
                </div>
                <div class="metric-stack">
                  <strong>${row.percentage}%</strong>
                  <span class="delta-label ${comparisonClass(row.delta_percentage_points)}">${formatDelta(row.delta_percentage_points)}</span>
                </div>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderPrizePoolFrequency(groups) {
  const container = document.getElementById("prize-pool-frequency");
  if (!groups.length) {
    container.innerHTML = document.getElementById("empty-state-template").innerHTML;
    return;
  }

  container.innerHTML = `
    <div class="frequency-grid">
      ${groups
        .map(
          (group) => `
            <article class="frequency-card">
              <div class="frequency-head">
                <strong>${centsToCurrency(group.buy_in_cents)}</strong>
                <span>${group.total_tournaments} турниров</span>
              </div>
              <div class="table-scroll frequency-scroll">
                <div class="frequency-table">
                  <div class="frequency-list">
                    ${group.rows
                      .map(
                        (row, _index, rows) => {
                          const scaleMax = Math.max(...rows.map((item) => item.percentage), 0);
                          return `
                          <div class="frequency-row ${comparisonClass(row.delta_percentage_points)}">
                            <span>${centsToCurrency(row.prize_pool_cents)}</span>
                            <div class="bar-cell">
                              <div class="bar-track">
                                ${row.expected_percentage !== null
                                  ? `<div class="bar-benchmark" style="left: ${benchmarkPosition(scaledPosition(row.expected_percentage, scaleMax))}%"></div>`
                                  : ""}
                                <div class="bar-fill ${comparisonClass(row.delta_percentage_points)}" style="width: ${Math.max(scaledPosition(row.percentage, scaleMax), 3)}%"></div>
                              </div>
                              <span>${row.count}</span>
                            </div>
                            <div class="metric-stack">
                              <strong>${row.percentage}%</strong>
                              <span class="delta-label ${comparisonClass(row.delta_percentage_points)}">
                                ${row.delta_percentage_points !== null
                                  ? `${formatDelta(row.delta_percentage_points)} к ожиданию`
                                  : "нет эталона"}
                              </span>
                            </div>
                          </div>
                        `;
                        }
                      )
                      .join("")}
                  </div>
                </div>
              </div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function renderBreakdown(containerId, rows, labelBuilder) {
  const container = document.getElementById(containerId);
  if (!rows.length) {
    container.innerHTML = document.getElementById("empty-state-template").innerHTML;
    return;
  }

  container.innerHTML = `
    <div class="table-scroll">
      <div class="mini-table">
        <div class="mini-table-head">
          <span>${labelBuilder.heading}</span>
          <span>Турниры</span>
          <span>Среднее место</span>
          <span>Побед</span>
        </div>
        ${rows
          .map(
            (row) => `
              <div class="mini-table-row">
                <strong>${escapeHtml(labelBuilder.value(row.value_cents))}</strong>
                <span>${row.tournaments}</span>
                <span>${row.average_place.toFixed(2)}</span>
                <span>${row.wins} (${row.win_rate}%)</span>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderRecent(tournaments) {
  const container = document.getElementById("recent-table");
  if (!tournaments.length) {
    container.innerHTML = document.getElementById("empty-state-template").innerHTML;
    return;
  }

  container.innerHTML = `
    <div class="table-scroll recent-scroll">
      <div class="mini-table mini-table-recent">
        <div class="mini-table-head recent-head">
          <span>Дата</span>
          <span>Турнир</span>
          <span>Бай-ин</span>
          <span>Призпул</span>
          <span>Место</span>
          <span>Выплата</span>
        </div>
        ${tournaments
          .map(
            (item) => `
              <div class="mini-table-row recent-row">
                <span>${escapeHtml(item.started_at.replace("T", " "))}</span>
                <span>${escapeHtml(item.tournament_name)} #${escapeHtml(item.tournament_id)}</span>
                <span>${centsToCurrency(item.buy_in_cents)}</span>
                <span>${centsToCurrency(item.prize_pool_cents)}</span>
                <strong>${item.place}</strong>
                <span>${centsToCurrency(item.payout_cents)}</span>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderBuyInOptions(buyIns) {
  const container = document.getElementById("buyin-options");
  container.innerHTML = buyIns
    .map((valueCents) => {
      const checked = state.selectedBuyIns.has(valueCents) ? "checked" : "";
      return `
        <label class="chip">
          <input type="checkbox" value="${valueCents}" ${checked}>
          <span>${centsToCurrency(valueCents)}</span>
        </label>
      `;
    })
    .join("");

  container.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.addEventListener("change", async (event) => {
      const value = Number(event.target.value);
      if (event.target.checked) {
        state.selectedBuyIns.add(value);
      } else {
        state.selectedBuyIns.delete(value);
      }
      await refreshDashboard();
    });
  });
}

function renderMultiplierOptions(multipliers) {
  const container = document.getElementById("multiplier-options");
  container.innerHTML = multipliers
    .map((value) => {
      const checked = state.selectedMultipliers.has(value) ? "checked" : "";
      return `
        <label class="chip">
          <input type="checkbox" value="${value}" ${checked}>
          <span>${value}x</span>
        </label>
      `;
    })
    .join("");

  container.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.addEventListener("change", async (event) => {
      const value = Number(event.target.value);
      if (event.target.checked) {
        state.selectedMultipliers.add(value);
      } else {
        state.selectedMultipliers.delete(value);
      }
      await refreshDashboard();
    });
  });
}

function renderWeekdayOptions(weekdays) {
  const container = document.getElementById("weekday-options");
  container.innerHTML = weekdays
    .map((value) => {
      const checked = state.selectedWeekdays.has(value) ? "checked" : "";
      const weekday = weekdayMetaByValue.get(value);
      const shortLabel = weekday ? weekday.shortLabel : value.toString();
      const fullLabel = weekday ? weekday.fullLabel : value.toString();
      return `
        <label class="chip" title="${escapeHtml(fullLabel)}">
          <input type="checkbox" value="${value}" ${checked}>
          <span>${escapeHtml(shortLabel)}</span>
        </label>
      `;
    })
    .join("");

  container.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.addEventListener("change", async (event) => {
      const value = Number(event.target.value);
      if (event.target.checked) {
        state.selectedWeekdays.add(value);
      } else {
        state.selectedWeekdays.delete(value);
      }
      await refreshDashboard();
    });
  });
}

function renderTimeSlotOptions(timeSlots) {
  const container = document.getElementById("time-slot-options");
  container.innerHTML = timeSlots
    .map((value) => {
      const checked = state.selectedTimeSlots.has(value) ? "checked" : "";
      const timeSlot = timeSlotMetaByValue.get(value);
      const label = timeSlot ? timeSlot.label : value;
      return `
        <label class="chip">
          <input type="checkbox" value="${escapeHtml(value)}" ${checked}>
          <span>${escapeHtml(label)}</span>
        </label>
      `;
    })
    .join("");

  container.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.addEventListener("change", async (event) => {
      const value = event.target.value;
      if (event.target.checked) {
        state.selectedTimeSlots.add(value);
      } else {
        state.selectedTimeSlots.delete(value);
      }
      await refreshDashboard();
    });
  });
}

function renderPrizePoolHints(prizePools) {
  const hints = prizePools
    .slice(0, 12)
    .map((valueCents) => `<button type="button" class="hint-pill" data-prize="${valueCents}">${centsToCurrency(valueCents)}</button>`)
    .join("");

  const container = document.getElementById("prize-pool-hints");
  container.innerHTML = hints;
  container.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", async () => {
      const dollars = (Number(button.dataset.prize) / 100).toString();
      document.getElementById("prize-pool-min").value = dollars;
      document.getElementById("prize-pool-max").value = dollars;
      state.prizePoolMin = dollars;
      state.prizePoolMax = dollars;
      await refreshDashboard();
    });
  });
}

function renderStartedAtBounds(filters) {
  const startedAtFromInput = document.getElementById("started-at-from");
  const startedAtToInput = document.getElementById("started-at-to");
  const minValue = toDateTimeLocalValue(filters.started_at_min);
  const maxValue = toDateTimeLocalValue(filters.started_at_max);

  startedAtFromInput.min = minValue;
  startedAtFromInput.max = maxValue;
  startedAtToInput.min = minValue;
  startedAtToInput.max = maxValue;
}

async function refreshDashboard() {
  const payload = await fetchDashboard();
  state.filters = payload.filters;
  renderBuyInOptions(payload.filters.buy_ins_cents);
  renderMultiplierOptions(payload.filters.multipliers);
  renderWeekdayOptions(payload.filters.weekdays || []);
  renderTimeSlotOptions(payload.filters.time_slots || []);
  renderPrizePoolHints(payload.filters.prize_pools_cents);
  renderStartedAtBounds(payload.filters);
  renderSummary(payload.summary);
  renderDistribution(payload.distribution, payload.summary.total_tournaments);
  renderPrizePoolFrequency(payload.prize_pool_frequency_by_buy_in);
  renderBreakdown("buyin-breakdown", payload.buy_in_breakdown, {
    heading: "Бай-ин",
    value: centsToCurrency,
  });
  renderBreakdown("prize-breakdown", payload.prize_pool_breakdown, {
    heading: "Призпул",
    value: centsToCurrency,
  });
  renderRecent(payload.recent_tournaments);
}

function wireInputs() {
  const minInput = document.getElementById("prize-pool-min");
  const maxInput = document.getElementById("prize-pool-max");
  const startedAtFromInput = document.getElementById("started-at-from");
  const startedAtToInput = document.getElementById("started-at-to");
  const resetButton = document.getElementById("reset-filters");
  const uploadForm = document.getElementById("upload-form");
  const archiveInput = document.getElementById("archive-input");
  const uploadStatus = document.getElementById("upload-status");

  async function handleRangeChange() {
    state.prizePoolMin = minInput.value.trim();
    state.prizePoolMax = maxInput.value.trim();
    await refreshDashboard();
  }

  minInput.addEventListener("change", handleRangeChange);
  maxInput.addEventListener("change", handleRangeChange);

  async function handleStartedAtChange() {
    state.startedAtFrom = startedAtFromInput.value;
    state.startedAtTo = startedAtToInput.value;
    await refreshDashboard();
  }

  startedAtFromInput.addEventListener("change", handleStartedAtChange);
  startedAtToInput.addEventListener("change", handleStartedAtChange);

  resetButton.addEventListener("click", async () => {
    state.selectedBuyIns.clear();
    state.selectedMultipliers.clear();
    state.selectedWeekdays.clear();
    state.selectedTimeSlots.clear();
    state.prizePoolMin = "";
    state.prizePoolMax = "";
    state.startedAtFrom = "";
    state.startedAtTo = "";
    minInput.value = "";
    maxInput.value = "";
    startedAtFromInput.value = "";
    startedAtToInput.value = "";
    await refreshDashboard();
  });

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!archiveInput.files.length) {
      uploadStatus.textContent = "Сначала выберите ZIP-архив.";
      return;
    }

    const formData = new FormData();
    [...archiveInput.files].forEach((file) => formData.append("archives", file));

    uploadStatus.textContent = "Импортирую архивы...";

    const response = await fetch("/api/import", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({ error: "Ошибка импорта." }));
      uploadStatus.textContent = errorPayload.error || "Ошибка импорта.";
      return;
    }

    const payload = await response.json();
    const imported = payload.results.reduce((total, item) => total + item.inserted_count, 0);
    const duplicates = payload.results.reduce((total, item) => total + item.duplicate_count, 0);
    uploadStatus.textContent = `Готово: добавлено ${imported}, дублей ${duplicates}.`;
    archiveInput.value = "";
    await refreshDashboard();
  });
}

async function bootstrap() {
  wireInputs();
  await refreshDashboard();
}

bootstrap().catch((error) => {
  document.getElementById("summary-grid").innerHTML = `
    <article class="summary-card error-card">
      <p class="summary-label">Ошибка</p>
      <h3 class="summary-value">Не удалось загрузить данные</h3>
      <p class="summary-note">${escapeHtml(error.message)}</p>
    </article>
  `;
});
