(() => {
  const MQTT_URL = "wss://broker.emqx.io:8084/mqtt";
  const MQTT_TOPIC = "akbaselif/motor-f407-a91c7e/telemetry";

  const connectionText = document.querySelector("#connectionText");
  const connectionDot = document.querySelector(".dot");
  const speedText = document.querySelector("#speedValue");
  const i2cText = document.querySelector("#i2cValue");
  const invalidText = document.querySelector("#invalidValue");

  let liveCount = 0;
  let previousMessageTime = 0;

  function setConnection(text, color) {
    connectionText.textContent = text;
    connectionDot.style.background = color;
    connectionDot.style.boxShadow = `0 0 0 3px ${color}22`;
  }

  function makeRow(data) {
    const row = {
      zaman: new Date().toLocaleTimeString("tr-TR"),
      seq: Number(data.seq ?? 0),

      rms_x_ug: Number(data.rms_x_ug ?? data.rms_x),
      rms_y_ug: Number(data.rms_y_ug ?? data.rms_y),
      rms_z_ug: Number(data.rms_z_ug ?? data.rms_z),
      rms_mag_ug: Number(data.rms_mag_ug ?? data.rms_mag),
      peak_ug: Number(data.peak_ug ?? data.peak),

      crest_x1000:
        data.crest_x1000 != null
          ? Number(data.crest_x1000)
          : Math.round(Number(data.crest) * 1000),

      i2c_err: Number(data.err ?? 0),
      gecerli: Number(data.err ?? 0) === 0 ? 1 : 0,
      motor: data.motor || "STM32F407",
      run: data.run ?? "Canlı"
    };

    const required = [
      "rms_x_ug",
      "rms_y_ug",
      "rms_z_ug",
      "rms_mag_ug",
      "peak_ug",
      "crest_x1000"
    ];

    if (required.some((key) => !Number.isFinite(row[key]))) {
      throw new Error("MQTT mesajında eksik veya hatalı ölçüm var.");
    }

    return row;
  }

  function showLiveRow(row) {
    clearInterval(timer);
    timer = null;

    const now = Date.now();

    if (previousMessageTime !== 0) {
      const speed = 1000 / (now - previousMessageTime);
      speedText.textContent = `${speed.toFixed(2)} pencere/s`;
    }

    previousMessageTime = now;
    liveCount += 1;

    visibleRows.push(row);

    if (visibleRows.length > MAX_POINTS) {
      visibleRows.shift();
    }

    updateMetrics(row);
    updateStatus(row);
    updateHistory(row);
    drawChart();

    ui.sourceName.textContent = "ESP8266 / MQTT";
    ui.motor.textContent = row.motor;
    ui.run.textContent = row.run;
    ui.window.textContent = `${liveCount} canlı pencere`;

    i2cText.textContent = row.i2c_err;
    invalidText.textContent = row.gecerli ? "0" : "1";

    setConnection("Canlı", "#26d980");
  }

  if (typeof mqtt === "undefined") {
    setConnection("MQTT.js yüklenemedi", "#ff4f56");
    console.error("MQTT.js bulunamadı.");
    return;
  }

  setConnection("MQTT bağlanıyor", "#ff9f1a");

  const client = mqtt.connect(MQTT_URL, {
    clientId: `motor-web-${Math.random().toString(16).slice(2, 10)}`,
    clean: true,
    connectTimeout: 10000,
    reconnectPeriod: 3000
  });

  client.on("connect", () => {
    setConnection("Bağlı, veri bekleniyor", "#26d980");

    client.subscribe(MQTT_TOPIC, { qos: 0 }, (error) => {
      if (error) {
        setConnection("Abonelik hatası", "#ff4f56");
        console.error(error);
      } else {
        console.log("MQTT topic dinleniyor:", MQTT_TOPIC);
      }
    });
  });

  client.on("message", (topic, payload) => {
    if (topic !== MQTT_TOPIC) return;

    try {
      const data = JSON.parse(payload.toString());
      const row = makeRow(data);
      showLiveRow(row);
    } catch (error) {
      console.error("Geçersiz MQTT mesajı:", payload.toString(), error);
    }
  });

  client.on("reconnect", () => {
    setConnection("Yeniden bağlanıyor", "#ff9f1a");
  });

  client.on("offline", () => {
    setConnection("Bağlantı kesildi", "#647786");
  });

  client.on("error", (error) => {
    setConnection("MQTT hatası", "#ff4f56");
    console.error("MQTT hatası:", error);
  });
})();