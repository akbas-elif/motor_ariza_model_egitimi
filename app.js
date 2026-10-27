const THRESHOLD = 838154;
const MAX_POINTS = 120;
const COLORS = { x: "#29a8ff", y: "#ff9f1a", z: "#26d980", mag: "#ff4f56" };

const ui = {
  canvas: document.querySelector("#trendChart"),
  statusRing: document.querySelector("#statusRing"),
  statusLabel: document.querySelector("#statusLabel"),
  statusRule: document.querySelector("#statusRule"),
  distance: document.querySelector("#distanceValue"),
  history: document.querySelector("#historyBody"),
  csvInput: document.querySelector("#csvInput"),
  demoButton: document.querySelector("#demoButton"),
  pauseButton: document.querySelector("#pauseButton"),
  resetButton: document.querySelector("#resetButton"),
  sourceName: document.querySelector("#sourceName"),
  motor: document.querySelector("#motorValue"),
  run: document.querySelector("#runValue"),
  window: document.querySelector("#windowValue"),
  connection: document.querySelector("#connectionText"),
};

const metricIds = {
  rms_x_ug: "rmsX",
  rms_y_ug: "rmsY",
  rms_z_ug: "rmsZ",
  rms_mag_ug: "rmsMag",
  peak_ug: "peak",
  crest_x1000: "crest",
};

let rows = [];
let visibleRows = [];
let cursor = 0;
let timer = null;

function makeDemoRows() {
  return Array.from({ length: 90 }, (_, index) => {
    const faulty = index >= 48;
    const base = faulty ? 1500000 : 255000;
    const wave = Math.sin(index * 0.45) * (faulty ? 38000 : 9000);
    const mag = Math.round(base + wave + Math.sin(index * 1.7) * 5000);
    return {
      zaman: new Date(Date.now() + index * 1030).toLocaleTimeString("tr-TR"),
      seq: 4400 + index,
      rms_x_ug: Math.round(mag * (faulty ? 0.28 : 0.33)),
      rms_y_ug: Math.round(mag * (faulty ? 0.71 : 0.55)),
      rms_z_ug: Math.round(mag * (faulty ? 0.65 : 0.77)),
      rms_mag_ug: mag,
      peak_ug: Math.round(mag * (faulty ? 1.47 : 1.91)),
      crest_x1000: faulty ? 1470 : 1910,
      gecerli: 1,
      i2c_err: 0,
      motor: faulty ? "B" : "A",
      run: faulty ? 7 : 4,
    };
  });
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("CSV içinde veri satırı bulunamadı.");
  const headers = lines[0].split(",").map((value) => value.trim());
  const required = ["rms_x_ug", "rms_y_ug", "rms_z_ug", "rms_mag_ug", "peak_ug", "crest_x1000"];
  const missing = required.filter((name) => !headers.includes(name));
  if (missing.length) throw new Error(`Eksik sütun: ${missing.join(", ")}`);

  return lines.slice(1).map((line) => {
    const values = line.split(",");
    const row = Object.fromEntries(headers.map((header, index) => [header, values[index]?.trim() ?? ""]));
    required.concat(["seq", "run", "gecerli", "i2c_err"]).forEach((key) => {
      if (key in row) row[key] = Number(row[key]);
    });
    return row;
  });
}

function setRows(newRows, sourceName) {
  stop();
  rows = newRows;
  visibleRows = [];
  cursor = 0;
  ui.sourceName.textContent = sourceName;
  ui.motor.textContent = rows[0]?.motor || "—";
  ui.run.textContent = rows[0]?.run ?? "—";
  ui.window.textContent = `0 / ${rows.length}`;
  ui.history.innerHTML = '<tr><td colspan="5" class="empty">Veri bekleniyor</td></tr>';
  drawChart();
}

function start() {
  if (!rows.length) setRows(makeDemoRows(), "Dahili demo");
  if (timer) return;
  ui.connection.textContent = "Aktif";
  timer = setInterval(tick, 1030);
}

function stop() {
  clearInterval(timer);
  timer = null;
  ui.connection.textContent = "Beklemede";
}

function reset() {
  stop();
  visibleRows = [];
  cursor = 0;
  ui.window.textContent = `0 / ${rows.length}`;
  ui.history.innerHTML = '<tr><td colspan="5" class="empty">Veri bekleniyor</td></tr>';
  updateStatus(null);
  drawChart();
}

function tick() {
  if (cursor >= rows.length) {
    stop();
    return;
  }
  const row = rows[cursor++];
  visibleRows.push(row);
  if (visibleRows.length > MAX_POINTS) visibleRows.shift();
  updateMetrics(row);
  updateStatus(row);
  updateHistory(row);
  ui.motor.textContent = row.motor || "—";
  ui.run.textContent = row.run ?? "—";
  ui.window.textContent = `${cursor} / ${rows.length}`;
  document.querySelector("#i2cValue").textContent = row.i2c_err || 0;
  document.querySelector("#invalidValue").textContent = rows.slice(0, cursor).filter((item) => Number(item.gecerli) === 0).length;
  drawChart();
}

function updateMetrics(row) {
  document.querySelector("#rmsX").textContent = formatNumber(row.rms_x_ug);
  document.querySelector("#rmsY").textContent = formatNumber(row.rms_y_ug);
  document.querySelector("#rmsZ").textContent = formatNumber(row.rms_z_ug);
  document.querySelector("#rmsMag").textContent = formatNumber(row.rms_mag_ug);
  document.querySelector("#peak").textContent = formatNumber(row.peak_ug);
  document.querySelector("#crest").textContent = (Number(row.crest_x1000) / 1000).toFixed(2);

  document.querySelectorAll(".metric").forEach((card) => {
    const key = card.dataset.metric;
    const max = Number(card.dataset.max);
    const percent = Math.min(100, Math.max(0, Number(row[key]) / max * 100));
    card.querySelector(".gauge").style.setProperty("--value", `${percent}%`);
  });
}

function updateStatus(row) {
  if (!row) {
    ui.statusRing.className = "status-ring normal";
    ui.statusLabel.textContent = "BEKLİYOR";
    ui.statusRule.textContent = "veri yok";
    ui.distance.textContent = "—";
    return;
  }
  const value = Number(row.rms_mag_ug);
  const faulty = value > THRESHOLD;
  ui.statusRing.className = `status-ring ${faulty ? "fault" : "normal"}`;
  ui.statusLabel.textContent = faulty ? "BOZUK" : "NORMAL";
  ui.statusRule.textContent = faulty ? "eşik üstünde" : "eşik altında";
  ui.distance.textContent = `${Math.abs((value - THRESHOLD) / THRESHOLD * 100).toFixed(1)}%`;
}

function updateHistory(row) {
  if (ui.history.querySelector(".empty")) ui.history.innerHTML = "";
  const faulty = Number(row.rms_mag_ug) > THRESHOLD;
  const tr = document.createElement("tr");
  tr.innerHTML = `<td>${escapeHtml(row.zaman || "—")}</td><td>${row.seq ?? "—"}</td><td class="${faulty ? "state-fault" : "state-normal"}">${faulty ? "Bozuk" : "Normal"}</td><td>${formatNumber(row.rms_mag_ug)} µg</td><td>${Number(row.gecerli) === 0 ? "Hatalı" : "OK"}</td>`;
  ui.history.prepend(tr);
  while (ui.history.children.length > 8) ui.history.lastElementChild.remove();
}

function drawChart() {
  const canvas = ui.canvas;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const width = rect.width;
  const height = rect.height;
  const pad = { left: 62, right: 18, top: 10, bottom: 35 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxY = Math.max(1800000, ...visibleRows.map((row) => Number(row.rms_mag_ug) || 0));

  ctx.clearRect(0, 0, width, height);
  ctx.font = "11px Segoe UI";
  ctx.strokeStyle = "#263746";
  ctx.fillStyle = "#91a3b4";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const y = pad.top + plotH * i / 5;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    const label = Math.round(maxY * (1 - i / 5));
    ctx.fillText(label.toLocaleString("tr-TR"), 4, y + 4);
  }
  for (let i = 0; i <= 6; i++) {
    const x = pad.left + plotW * i / 6;
    ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, height - pad.bottom); ctx.stroke();
  }
  ctx.fillText("Son pencereler", width / 2 - 35, height - 8);

  const series = [
    ["rms_x_ug", COLORS.x], ["rms_y_ug", COLORS.y], ["rms_z_ug", COLORS.z], ["rms_mag_ug", COLORS.mag],
  ];
  series.forEach(([key, color]) => {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    visibleRows.forEach((row, index) => {
      const x = pad.left + (visibleRows.length <= 1 ? 0 : index / (visibleRows.length - 1)) * plotW;
      const y = pad.top + plotH - (Number(row[key]) / maxY) * plotH;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function formatNumber(value) { return Number(value || 0).toLocaleString("tr-TR"); }
function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

ui.csvInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    setRows(parseCsv(await file.text()), file.name);
    start();
  } catch (error) {
    alert(error.message);
  }
});
ui.demoButton.addEventListener("click", () => { setRows(makeDemoRows(), "Dahili demo"); start(); });
ui.pauseButton.addEventListener("click", () => timer ? stop() : start());
ui.resetButton.addEventListener("click", reset);
window.addEventListener("resize", drawChart);

setRows(makeDemoRows(), "Dahili demo");
updateStatus(null);
