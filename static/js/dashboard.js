(function () {
  var raw = document.getElementById("chart-data");
  if (!raw || !window.Chart) return;
  var data = JSON.parse(raw.textContent);

  Chart.defaults.font.family = '"IBM Plex Sans", system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#667085";
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.plugins.legend.labels.pointStyle = "circle";

  var grid = { color: "#eceff5", drawTicks: false };
  var noBorder = { display: false };

  function empty(id, text) {
    var canvas = document.getElementById(id);
    var box = canvas.parentElement;
    box.innerHTML = '<div class="mini-empty d-flex align-items-center justify-content-center h-100">' + text + "</div>";
  }

  // 1. Output trend, two axes because yarn is kg and fabric is metres
  var t = data.trend;
  new Chart(document.getElementById("trendChart"), {
    type: "line",
    data: {
      labels: t.labels,
      datasets: t.datasets.map(function (d) {
        return {
          label: d.label, data: d.data, yAxisID: d.yAxisID, borderColor: d.color, backgroundColor: d.color,
          borderWidth: 2, tension: 0.3, pointRadius: 2.5, pointHoverRadius: 5,
          borderDash: d.yAxisID === "yKg" ? [5, 4] : [],
        };
      }),
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { grid: noBorder, border: noBorder, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 24 } },
        yM: { position: "left", beginAtZero: true, grid: grid, border: noBorder, title: { display: true, text: "metres" } },
        yKg: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false }, border: noBorder, title: { display: true, text: "kg" } },
      },
    },
  });

  // 2. Downtime hours by reason
  if (data.downtime.data.length) {
    new Chart(document.getElementById("downtimeChart"), {
      type: "bar",
      data: { labels: data.downtime.labels, datasets: [{ data: data.downtime.data, backgroundColor: "#c0392b", borderRadius: 4, maxBarThickness: 22 }] },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return c.parsed.x + " h"; } } } },
        scales: { x: { beginAtZero: true, grid: grid, border: noBorder }, y: { grid: noBorder, border: noBorder } },
      },
    });
  } else { empty("downtimeChart", "No downtime recorded in the last 30 days."); }

  // 3. Defects by type
  if (data.defects.data.length) {
    new Chart(document.getElementById("defectChart"), {
      type: "bar",
      data: { labels: data.defects.labels, datasets: [{ data: data.defects.data, backgroundColor: "#3149c6", borderRadius: 4, maxBarThickness: 22 }] },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return c.parsed.x + " m"; } } } },
        scales: { x: { beginAtZero: true, grid: grid, border: noBorder }, y: { grid: noBorder, border: noBorder } },
      },
    });
  } else { empty("defectChart", "No defects recorded in the last 30 days."); }
})();
