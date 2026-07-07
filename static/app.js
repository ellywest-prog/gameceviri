/**
 * Apex Çeviri – Frontend Application
 * Push-to-Talk: T tuşu (global) + UI buton
 */

// ============================================================
// State
// ============================================================
const state = {
    ws: null,
    connected: false,         // OpenAI'ye bağlı mı
    recording: false,         // PTT aktif mi
    devices: { input: [], output: [] },
    totalMinutes: 0,
    totalCost: 0,

    // Current transcript being built
    currentTR: "",
    currentEN: "",
};

// ============================================================
// DOM References
// ============================================================
const $ = (sel) => document.querySelector(sel);

const dom = {
    apiKey:         $("#apiKey"),
    toggleApiKey:   $("#toggleApiKey"),
    testApiKey:     $("#testApiKey"),
    apiTestResult:  $("#apiTestResult"),
    inputDevice:    $("#inputDevice"),
    outputDevice:   $("#outputDevice"),
    connectBtn:     $("#connectBtn"),
    connectHint:    $("#connectHint"),
    connectionBadge: $("#connectionBadge"),
    statusIcon:     $("#statusIcon"),
    statusText:     $("#statusText"),
    pttButton:      $("#pttButton"),
    transcriptLog:  $("#transcriptLog"),
    clearLog:       $("#clearLog"),
    totalTime:      $("#totalTime"),
    totalCost:      $("#totalCost"),
    shutdownBtn:    $("#shutdownBtn"),
    shutdownOverlay: $("#shutdownOverlay"),
};

const API_KEY_STORAGE = "apex_api_key";

// ============================================================
// Toast Notifications
// ============================================================
function showToast(message, type = "info", duration = 4000) {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(20px)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ============================================================
// Device Loading
// ============================================================
async function loadDevices() {
    try {
        const res = await fetch("/api/devices");
        state.devices = await res.json();

        populateSelect(dom.inputDevice, state.devices.input, "input");
        populateSelect(dom.outputDevice, state.devices.output, "output");

        // Restore saved selections
        const savedInput = localStorage.getItem("apex_input_device");
        const savedOutput = localStorage.getItem("apex_output_device");

        if (savedInput && dom.inputDevice.querySelector(`option[value="${savedInput}"]`)) {
            dom.inputDevice.value = savedInput;
        }
        if (savedOutput && dom.outputDevice.querySelector(`option[value="${savedOutput}"]`)) {
            dom.outputDevice.value = savedOutput;
        }

        // Auto-select CABLE device for output
        if (!savedOutput) {
            for (const dev of state.devices.output) {
                if (dev.name.toUpperCase().includes("CABLE")) {
                    dom.outputDevice.value = dev.index;
                    localStorage.setItem("apex_output_device", dev.index);
                    break;
                }
            }
        }

        // Auto-select default/first input device if nothing saved
        if (!savedInput || !dom.inputDevice.querySelector(`option[value="${savedInput}"]`)) {
            const defaultInput = state.devices.input.find(d => d.is_default)
                || state.devices.input[0];
            if (defaultInput) {
                dom.inputDevice.value = defaultInput.index;
                localStorage.setItem("apex_input_device", defaultInput.index);
            }
        }

        updateConnectButton();
    } catch (err) {
        showToast("Ses cihazları yüklenemedi!", "error");
        console.error("Device load error:", err);
    }
}

function populateSelect(selectEl, devices, type) {
    selectEl.innerHTML = "";

    if (devices.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Cihaz bulunamadı";
        selectEl.appendChild(opt);
        return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = type === "input" ? "Mikrofon seçin..." : "Çıkış cihazı seçin...";
    placeholder.disabled = true;
    placeholder.selected = true;
    selectEl.appendChild(placeholder);

    for (const dev of devices) {
        const opt = document.createElement("option");
        opt.value = dev.index;
        opt.textContent = dev.name;
        selectEl.appendChild(opt);
    }
}

// ============================================================
// WebSocket Connection (to Python backend)
// ============================================================
function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log("Backend WebSocket connected");
    };

    state.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };

    state.ws.onclose = () => {
        console.log("Backend WebSocket closed");
        state.connected = false;
        state.recording = false;
        updateUI("disconnected");

        // Reconnect after 2 seconds
        setTimeout(connectWebSocket, 2000);
    };

    state.ws.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

function sendMessage(data) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(data));
    }
}

// ============================================================
// Server Message Handler
// ============================================================
function handleServerMessage(data) {
    switch (data.type) {
        case "status":
            updateUI(data.state);
            if (data.state === "idle" || data.state === "connected") {
                state.connected = true;
                state.recording = false;
            } else if (data.state === "recording") {
                state.recording = true;
            } else if (data.state === "translating") {
                state.recording = false;
            } else if (data.state === "disconnected") {
                state.connected = false;
                state.recording = false;
            }
            break;

        case "transcript":
            handleTranscript(data);
            break;

        case "error":
            showToast(data.message, "error", 6000);
            break;

        case "cost":
            state.totalMinutes = data.minutes;
            state.totalCost = data.cost_usd;
            updateCostDisplay();
            break;


    }
}

// ============================================================
// Transcript Handling
// ============================================================
function handleTranscript(data) {
    const log = dom.transcriptLog;

    // Remove empty state message
    const emptyMsg = log.querySelector(".transcript-empty");
    if (emptyMsg) emptyMsg.remove();

    if (data.lang === "tr") {
        // Streaming Turkish transcription delta
        state.currentTR += data.text;
        updateActiveEntry();
    } else if (data.lang === "tr_final") {
        // Final Turkish transcription
        state.currentTR = data.text;
        updateActiveEntry();
    } else if (data.lang === "en") {
        // Streaming English translation delta
        state.currentEN += data.text;
        updateActiveEntry();
    } else if (data.lang === "en_final") {
        // Final English translation
        state.currentEN = data.text;
        finalizeEntry();
    }
}

function updateActiveEntry() {
    const log = dom.transcriptLog;
    let activeEntry = log.querySelector(".transcript-entry.active");

    if (!activeEntry) {
        activeEntry = document.createElement("div");
        activeEntry.className = "transcript-entry active";
        activeEntry.innerHTML = `
            <div class="tr-line"><span class="lang-tag">TR</span><span class="tr-text"></span></div>
            <div class="en-line"><span class="lang-tag">EN</span><span class="en-text"></span></div>
        `;
        log.appendChild(activeEntry);
    }

    if (state.currentTR) {
        activeEntry.querySelector(".tr-text").textContent = state.currentTR;
    }
    if (state.currentEN) {
        activeEntry.querySelector(".en-text").textContent = state.currentEN;
    }

    // Auto-scroll
    log.scrollTop = log.scrollHeight;
}

function finalizeEntry() {
    const log = dom.transcriptLog;
    const activeEntry = log.querySelector(".transcript-entry.active");

    if (activeEntry) {
        activeEntry.classList.remove("active");

        if (state.currentTR) {
            activeEntry.querySelector(".tr-text").textContent = state.currentTR;
        }
        if (state.currentEN) {
            activeEntry.querySelector(".en-text").textContent = state.currentEN;
        }
    }

    // Reset for next entry
    state.currentTR = "";
    state.currentEN = "";

    log.scrollTop = log.scrollHeight;
}

// ============================================================
// UI Updates
// ============================================================
const STATUS_MAP = {
    disconnected:  { icon: "⏸️", text: "Bağlantı yok", badge: "Bağlantı Yok" },
    connecting:    { icon: "🔄", text: "Bağlanılıyor...", badge: "Bağlanıyor..." },
    idle:          { icon: "✅", text: "Hazır – T tuşuna bas ve konuş!", badge: "Bağlı" },
    connected:     { icon: "✅", text: "Hazır – T tuşuna bas ve konuş!", badge: "Bağlı" },
    recording:     { icon: "🔴", text: "Kayıt yapılıyor... Konuş!", badge: "Kayıt" },
    translating:   { icon: "🔄", text: "Çevriliyor...", badge: "Çeviri" },
    error:         { icon: "❌", text: "Hata oluştu", badge: "Hata" },
};

function updateUI(statusState) {
    const info = STATUS_MAP[statusState] || STATUS_MAP.disconnected;

    dom.statusIcon.textContent = info.icon;
    dom.statusText.textContent = info.text;
    dom.connectionBadge.setAttribute("data-state", statusState);
    dom.connectionBadge.querySelector(".badge-text").textContent = info.badge;

    // PTT button state
    const isRecording = statusState === "recording";
    dom.pttButton.setAttribute("data-recording", isRecording);
    dom.pttButton.disabled = !state.connected;

    // Connect button
    if (statusState === "idle" || statusState === "connected" || statusState === "recording" || statusState === "translating") {
        dom.connectBtn.setAttribute("data-connected", "true");
        dom.connectBtn.querySelector(".btn-icon").textContent = "🔌";
        dom.connectBtn.querySelector(".btn-text").textContent = "Bağlantıyı Kes";
        dom.connectBtn.disabled = false;
    } else if (statusState === "connecting") {
        dom.connectBtn.disabled = true;
        dom.connectBtn.querySelector(".btn-text").textContent = "Bağlanıyor...";
    } else {
        dom.connectBtn.setAttribute("data-connected", "false");
        dom.connectBtn.querySelector(".btn-icon").textContent = "🔗";
        dom.connectBtn.querySelector(".btn-text").textContent = "Bağlan";
        updateConnectButton();
    }
}

function updateConnectButton() {
    const hasKey = dom.apiKey.value.trim().length > 0;
    const hasInput = dom.inputDevice.value !== "";
    const hasOutput = dom.outputDevice.value !== "";

    // Connect button: needs all three
    dom.connectBtn.disabled = !(hasKey && hasInput && hasOutput);

    // Show what's missing so the user knows why Bağlan is disabled
    const missing = [];
    if (!hasKey) missing.push("API key");
    if (!hasInput) missing.push("mikrofon");
    if (!hasOutput) missing.push("çıkış cihazı");
    if (dom.connectHint) {
        dom.connectHint.textContent = missing.length === 0
            ? "Hazır! Bağlan'a tıkla."
            : `Eksik: ${missing.join(", ")}`;
        dom.connectHint.classList.toggle("ready", missing.length === 0);
    }

    // API key test button: only needs a (sk-) looking key
    const keyOk = dom.apiKey.value.trim().startsWith("sk-");
    dom.testApiKey.disabled = !keyOk;

    // Reset the test result when the key changes after a test
    if (dom.apiTestResult.dataset.tested === "true" && dom.apiTestResult.dataset.lastKey !== dom.apiKey.value.trim()) {
        dom.apiTestResult.textContent = "";
        dom.apiTestResult.className = "api-test-result";
        delete dom.apiTestResult.dataset.tested;
        delete dom.apiTestResult.dataset.lastKey;
    }
}

// ============================================================
// API Key Test
// ============================================================
async function testApiKey() {
    const key = dom.apiKey.value.trim();
    if (!key.startsWith("sk-")) {
        setApiTestResult(false, "API key 'sk-' ile baslamali.");
        return;
    }

    dom.testApiKey.disabled = true;
    const originalText = dom.testApiKey.textContent;
    dom.testApiKey.textContent = "⏳ Test ediliyor...";
    dom.apiTestResult.textContent = "";
    dom.apiTestResult.className = "api-test-result";

    try {
        const res = await fetch(`/api/test-key?key=${encodeURIComponent(key)}`);
        const data = await res.json();
        if (res.ok && data.valid) {
            setApiTestResult(true, data.message || "API key gecerli!");
            showToast("API key doğrulandı ✅", "success");
        } else {
            setApiTestResult(false, data.message || `Hata: HTTP ${res.status}`);
        }
    } catch (err) {
        setApiTestResult(false, `Baglanti hatasi: ${err.message}`);
    } finally {
        dom.testApiKey.disabled = false;
        dom.testApiKey.textContent = originalText;
    }
}

function setApiTestResult(ok, message) {
    dom.apiTestResult.textContent = message;
    dom.apiTestResult.className = `api-test-result ${ok ? "ok" : "err"}`;
    dom.apiTestResult.dataset.tested = "true";
    dom.apiTestResult.dataset.lastKey = dom.apiKey.value.trim();
}

function updateCostDisplay() {
    const mins = Math.floor(state.totalMinutes);
    const secs = Math.round((state.totalMinutes - mins) * 60);
    dom.totalTime.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
    dom.totalCost.textContent = `$${state.totalCost.toFixed(2)}`;
}

// ============================================================
// Event Handlers
// ============================================================
function setupEventListeners() {
    // API key toggle visibility
    dom.toggleApiKey.addEventListener("click", () => {
        const isPassword = dom.apiKey.type === "password";
        dom.apiKey.type = isPassword ? "text" : "password";
        dom.toggleApiKey.textContent = isPassword ? "🙈" : "👁️";
    });

    // API key test button
    dom.testApiKey.addEventListener("click", () => {
        if (!dom.testApiKey.disabled) testApiKey();
    });

    // Form change → update connect button + persist API key
    dom.apiKey.addEventListener("input", () => {
        localStorage.setItem(API_KEY_STORAGE, dom.apiKey.value.trim());
        updateConnectButton();
    });
    dom.inputDevice.addEventListener("change", () => {
        localStorage.setItem("apex_input_device", dom.inputDevice.value);
        updateConnectButton();
    });
    dom.outputDevice.addEventListener("change", () => {
        localStorage.setItem("apex_output_device", dom.outputDevice.value);
        updateConnectButton();
    });

    // Connect / Disconnect
    dom.connectBtn.addEventListener("click", () => {
        if (dom.connectBtn.getAttribute("data-connected") === "true") {
            sendMessage({ type: "disconnect" });
            state.connected = false;
            state.recording = false;
            updateUI("disconnected");
        } else {
            sendMessage({
                type: "connect",
                api_key: dom.apiKey.value.trim(),
                input_device: parseInt(dom.inputDevice.value),
                output_device: parseInt(dom.outputDevice.value),
            });
            updateUI("connecting");
        }
    });

    // Shutdown Button
    dom.shutdownBtn.addEventListener("click", async () => {
        if (confirm("Uygulamayı kapatmak istediğinizden emin misiniz? Sunucu sonlandırılacaktır.")) {
            // Show overlay blocker
            dom.shutdownOverlay.classList.remove("hidden");
            
            // Try WebSocket first, fallback to HTTP POST if not connected
            if (ws && ws.readyState === WebSocket.OPEN) {
                try {
                    ws.send(JSON.stringify({ type: "shutdown" }));
                } catch (e) {
                    console.error("WS shutdown failed, falling back to HTTP", e);
                    await fetch("/api/shutdown", { method: "POST" }).catch(() => {});
                }
            } else {
                await fetch("/api/shutdown", { method: "POST" }).catch(() => {});
            }
        }
    });

    // PTT Button – Mouse events
    dom.pttButton.addEventListener("mousedown", (e) => {
        e.preventDefault();
        pttStart();
    });

    dom.pttButton.addEventListener("mouseup", () => {
        pttStop();
    });

    dom.pttButton.addEventListener("mouseleave", () => {
        if (state.recording) pttStop();
    });

    // PTT – Keyboard: T key (works when browser is focused)
    document.addEventListener("keydown", (e) => {
        if (e.key === "t" || e.key === "T") {
            // Don't trigger if typing in input fields
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
                return;
            }
            if (!e.repeat) {
                pttStart();
            }
        }
    });

    document.addEventListener("keyup", (e) => {
        if (e.key === "t" || e.key === "T") {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") {
                return;
            }
            pttStop();
        }
    });

    // Clear log
    dom.clearLog.addEventListener("click", () => {
        dom.transcriptLog.innerHTML = `
            <div class="transcript-empty">
                Henüz çeviri yok. Bağlanıp konuşmaya başla!
            </div>
        `;
    });

    // Prevent context menu on PTT button
    dom.pttButton.addEventListener("contextmenu", (e) => e.preventDefault());
}

// ============================================================
// Push-to-Talk Logic
// ============================================================
function pttStart() {
    if (!state.connected || state.recording) return;
    state.recording = true;
    sendMessage({ type: "ptt_start" });
    updateUI("recording");
}

function pttStop() {
    if (!state.recording) return;
    state.recording = false;
    sendMessage({ type: "ptt_stop" });
    updateUI("translating");
}

// ============================================================
// Init
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
    // Restore saved API key
    const savedApiKey = localStorage.getItem(API_KEY_STORAGE);
    if (savedApiKey) {
        dom.apiKey.value = savedApiKey;
    }

    loadDevices();
    setupEventListeners();
    updateConnectButton();
    connectWebSocket();
});
