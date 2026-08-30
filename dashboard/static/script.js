/**
 * INDUSTRIAL MIND — DUAL SIDE-BY-SIDE MONITORING CONTROLLER
 */

document.addEventListener("DOMContentLoaded", () => {
    let cpuChart = null;

    // DOM Elements
    const kpiTotalEl = document.getElementById("kpi-total");
    const kpiPassEl = document.getElementById("kpi-pass");
    const kpiDropEl = document.getElementById("kpi-drop");

    const tbodyScadaPlc = document.getElementById("tbody-scada-plc");
    const tbodyPlcScada = document.getElementById("tbody-plc-scada");

    const valPressure = document.getElementById("val-pressure");
    const valSpeed = document.getElementById("val-speed");
    const valValve = document.getElementById("val-valve");
    const barPressure = document.getElementById("bar-pressure");
    const barSpeed = document.getElementById("bar-speed");
    const barValve = document.getElementById("bar-valve");

    const valCpuLoad = document.getElementById("val-cpu-load");

    const btnTriggerAttack = document.getElementById("btn-trigger-attack");
    const btnResetData = document.getElementById("btn-reset-data");

    // ==========================================
    // 1. CHART INITIALIZATION
    // ==========================================
    function initCpuChart() {
        const canvas = document.getElementById("cpuLoadChart");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");

        cpuChart = new Chart(ctx, {
            type: "line",
            data: {
                labels: [],
                datasets: [{
                    label: "CPU Load (%)",
                    data: [],
                    borderColor: "#0ea5e9",
                    borderWidth: 2,
                    backgroundColor: "rgba(14, 165, 233, 0.08)",
                    fill: true,
                    tension: 0.2,
                    pointRadius: 2,
                    pointBackgroundColor: "#0ea5e9"
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 250 },
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 10 } }
                    },
                    y: {
                        min: 0,
                        max: 100,
                        grid: { color: "rgba(255, 255, 255, 0.05)" },
                        ticks: {
                            color: "#64748b",
                            font: { family: "JetBrains Mono", size: 10 },
                            callback: (v) => `${v}%`
                        }
                    }
                }
            }
        });
    }

    initCpuChart();

    // Helper to render table rows
    function renderTableRows(tbody, logItems) {
        if (!tbody || !logItems) return;
        tbody.innerHTML = "";
        logItems.forEach((item) => {
            const tr = document.createElement("tr");
            const verdictClass = item.verdict === "PASS" ? "PASS" : "DROP";
            const reasonClass = item.verdict === "DROP" ? "drop-reason" : "";

            tr.innerHTML = `
                <td style="color: #64748b; font-family: var(--font-mono);">${item.timestamp}</td>
                <td class="tx-id">${item.tx_id}</td>
                <td class="cmd-name">${item.command}</td>
                <td><span class="badge ${verdictClass}">${item.verdict}</span></td>
                <td class="reason-text ${reasonClass}">${item.reason}</td>
                <td class="latency">${item.latency_ms} ms</td>
            `;
            tbody.appendChild(tr);
        });
    }

    // ==========================================
    // 2. FETCH DATA & UPDATE UNIFIED DASHBOARD
    // ==========================================
    async function updateDashboardData() {
        try {
            const response = await fetch("/api/dashboard");
            if (!response.ok) return;
            const data = await response.json();

            // A. Update Overview Cards
            if (data.overview) {
                if (kpiTotalEl) kpiTotalEl.textContent = data.overview.total_requests.toLocaleString();
                if (kpiPassEl) kpiPassEl.textContent = data.overview.pass.toLocaleString();
                if (kpiDropEl) kpiDropEl.textContent = data.overview.drop.toLocaleString();
            }

            // B. Update Left Table (SCADA -> PLC)
            if (data.scada_to_plc && tbodyScadaPlc) {
                renderTableRows(tbodyScadaPlc, data.scada_to_plc);
            }

            // C. Update Right Table (PLC -> SCADA)
            if (data.plc_to_scada && tbodyPlcScada) {
                renderTableRows(tbodyPlcScada, data.plc_to_scada);
            }

            // D. Update Telemetry
            if (data.telemetry && data.telemetry.registers) {
                const reg = data.telemetry.registers;
                if (valPressure) valPressure.textContent = `${reg.TANK_PRESSURE.toFixed(0)} PSI`;
                if (barPressure) barPressure.style.width = `${Math.min(100, Math.max(0, reg.TANK_PRESSURE))}%`;

                if (valSpeed) valSpeed.textContent = `${reg.CONVEYOR_SPEED.toFixed(0)} RPM`;
                if (barSpeed) barSpeed.style.width = `${Math.min(100, Math.max(0, (reg.CONVEYOR_SPEED / 120) * 100))}%`;

                if (valValve) valValve.textContent = `${reg.COOLING_VALVE.toFixed(0)}°`;
                if (barValve) barValve.style.width = `${Math.min(100, Math.max(0, (reg.COOLING_VALVE / 90) * 100))}%`;
            }

            // E. Update CPU Load Chart
            if (cpuChart && data.cpu_history && data.telemetry) {
                const currentCpu = data.telemetry.cpu_load;
                if (valCpuLoad) valCpuLoad.textContent = `${currentCpu.toFixed(0)}%`;

                const labels = data.cpu_history.map(h => h.time);
                const points = data.cpu_history.map(h => h.cpu_load);

                cpuChart.data.labels = labels;
                cpuChart.data.datasets[0].data = points;

                if (currentCpu > 60) {
                    cpuChart.data.datasets[0].borderColor = "#f43f5e";
                    cpuChart.data.datasets[0].pointBackgroundColor = "#f43f5e";
                } else {
                    cpuChart.data.datasets[0].borderColor = "#0ea5e9";
                    cpuChart.data.datasets[0].pointBackgroundColor = "#0ea5e9";
                }
                cpuChart.update();
            }

        } catch (err) {
            console.error("[Dashboard Fetch Error]", err);
        }
    }

    // ==========================================
    // 3. ACTION BUTTONS
    // ==========================================
    if (btnTriggerAttack) {
        btnTriggerAttack.addEventListener("click", async () => {
            try {
                btnTriggerAttack.disabled = true;
                btnTriggerAttack.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Injecting...`;
                await fetch("/api/trigger-attack", { method: "POST" });
                await updateDashboardData();
            } catch (err) {
                console.error("[Attack Error]", err);
            } finally {
                setTimeout(() => {
                    btnTriggerAttack.disabled = false;
                    btnTriggerAttack.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Inject Attack`;
                }, 800);
            }
        });
    }

    if (btnResetData) {
        btnResetData.addEventListener("click", async () => {
            if (!confirm("Reset telemetry & metrics baseline?")) return;
            try {
                await fetch("/api/reset", { method: "POST" });
                await updateDashboardData();
            } catch (err) {
                console.error("[Reset Error]", err);
            }
        });
    }

    // Initial load & 2-second update loop
    updateDashboardData();
    setInterval(updateDashboardData, 2000);
});
