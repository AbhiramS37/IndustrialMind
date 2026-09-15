// =========================================================
// INDUSTRIAL MIND DASHBOARD
// =========================================================

let cpuChart = null;


// =========================================================
// FETCH DASHBOARD DATA
// =========================================================

async function refreshDashboard() {

    try {

        const response = await fetch(
            "/api/dashboard",
            {
                cache: "no-store"
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const data = await response.json();

        updateOverview(
            data.overview || {}
        );

        updateScadaToPlc(
            data.scada_to_plc || []
        );

        updatePlcToScada(
            data.plc_to_scada || []
        );

        updateTelemetry(
            data.telemetry || {}
        );

        updateCpuChart(
            data.cpu_history || []
        );

        updateCpuValue(
            data.telemetry || {}
        );

    } catch (error) {

        console.error(
            "Dashboard update failed:",
            error
        );
    }
}


// =========================================================
// OVERVIEW
// =========================================================

function updateOverview(overview) {

    const total =
        document.getElementById(
            "kpi-total"
        );

    const pass =
        document.getElementById(
            "kpi-pass"
        );

    const drop =
        document.getElementById(
            "kpi-drop"
        );

    if (total) {

        total.textContent =
            overview.total_requests ?? 0;
    }

    if (pass) {

        pass.textContent =
            overview.pass ?? 0;
    }

    if (drop) {

        drop.textContent =
            overview.drop ?? 0;
    }
}


// =========================================================
// SCADA -> PLC TABLE
// =========================================================

function updateScadaToPlc(events) {

    const tbody =
        document.getElementById(
            "tbody-scada-plc"
        );

    if (!tbody) {
        return;
    }

    tbody.innerHTML = "";

    events.forEach(event => {

        const row =
            document.createElement(
                "tr"
            );

        const verdict =
            String(
                event.verdict || "UNKNOWN"
            ).toUpperCase();

        row.innerHTML = `
            <td>${safe(event.timestamp)}</td>

            <td>
                <span class="transaction-id">
                    ${safe(event.tx_id)}
                </span>
            </td>

            <td>${safe(event.command)}</td>

            <td>
                <span class="verdict ${verdictClass(verdict)}">
                    ${safe(verdict)}
                </span>
            </td>

            <td>${safe(event.reason)}</td>

            <td>
                ${formatLatency(event.latency_ms)}
            </td>
        `;

        tbody.appendChild(row);
    });
}


// =========================================================
// PLC -> SCADA TABLE
// =========================================================

function updatePlcToScada(events) {

    const tbody =
        document.getElementById(
            "tbody-plc-scada"
        );

    if (!tbody) {
        return;
    }

    tbody.innerHTML = "";

    events.forEach(event => {

        const row =
            document.createElement(
                "tr"
            );

        const verdict =
            String(
                event.verdict || "PASS"
            ).toUpperCase();

        row.innerHTML = `
            <td>${safe(event.timestamp)}</td>

            <td>
                <span class="transaction-id">
                    ${safe(event.tx_id)}
                </span>
            </td>

            <td>${safe(event.command)}</td>

            <td>
                <span class="verdict ${verdictClass(verdict)}">
                    ${safe(verdict)}
                </span>
            </td>

            <td>${safe(event.reason)}</td>

            <td>
                ${formatLatency(event.latency_ms)}
            </td>
        `;

        tbody.appendChild(row);
    });
}


// =========================================================
// TELEMETRY
// =========================================================

function updateTelemetry(telemetry) {

    const registers =
        telemetry.registers || {};

    // -----------------------------
    // Tank Pressure
    // -----------------------------

    const pressure =
        Number(
            registers.TANK_PRESSURE ?? 0
        );

    setText(
        "val-pressure",
        `${pressure.toFixed(1)} PSI`
    );

    setBar(
        "bar-pressure",
        pressure,
        100
    );


    // -----------------------------
    // Conveyor Speed
    // -----------------------------

    const speed =
        Number(
            registers.CONVEYOR_SPEED ?? 0
        );

    setText(
        "val-speed",
        `${speed.toFixed(1)} RPM`
    );

    setBar(
        "bar-speed",
        speed,
        120
    );


    // -----------------------------
    // Cooling Valve
    // -----------------------------

    const valve =
        Number(
            registers.COOLING_VALVE ?? 0
        );

    setText(
        "val-valve",
        `${valve.toFixed(1)}°`
    );

    setBar(
        "bar-valve",
        valve,
        90
    );
}


// =========================================================
// CPU VALUE
// =========================================================

function updateCpuValue(telemetry) {

    const element =
        document.getElementById(
            "val-cpu-load"
        );

    if (!element) {
        return;
    }

    const value =
        Number(
            telemetry.cpu_load ?? 0
        );

    element.textContent =
        `${value.toFixed(1)}%`;
}


// =========================================================
// BAR UPDATE
// =========================================================

function setBar(
    id,
    value,
    maximum
) {

    const element =
        document.getElementById(id);

    if (!element) {
        return;
    }

    const percentage =
        Math.max(
            0,
            Math.min(
                100,
                (value / maximum) * 100
            )
        );

    element.style.width =
        `${percentage}%`;
}


// =========================================================
// CPU GRAPH
// =========================================================

function updateCpuChart(history) {

    const canvas =
        document.getElementById(
            "cpuLoadChart"
        );

    if (!canvas) {
        return;
    }

    if (typeof Chart === "undefined") {

        console.error(
            "Chart.js is not loaded."
        );

        return;
    }

    const labels =
        history.map(
            point => point.time
        );

    const values =
        history.map(
            point =>
                Number(point.value)
        );

    if (cpuChart) {

        cpuChart.data.labels =
            labels;

        cpuChart.data.datasets[0].data =
            values;

        cpuChart.update(
            "none"
        );

        return;
    }

    const ctx =
        canvas.getContext(
            "2d"
        );

    cpuChart =
        new Chart(
            ctx,
            {
                type: "line",

                data: {

                    labels: labels,

                    datasets: [
                        {
                            label:
                                "CPU Load (%)",

                            data: values,

                            borderWidth: 2,

                            fill: true,

                            tension: 0.3,

                            pointRadius: 0
                        }
                    ]
                },

                options: {

                    responsive: true,

                    maintainAspectRatio:
                        false,

                    animation: false,

                    scales: {

                        x: {
                            ticks: {
                                maxTicksLimit: 8
                            }
                        },

                        y: {

                            beginAtZero: true,

                            min: 0,

                            max: 100,

                            ticks: {

                                callback:
                                    value =>
                                        `${value}%`
                            }
                        }
                    },

                    plugins: {

                        legend: {
                            display: false
                        }
                    }
                }
            }
        );
}


// =========================================================
// HELPERS
// =========================================================

function setText(
    id,
    value
) {

    const element =
        document.getElementById(id);

    if (element) {

        element.textContent =
            value;
    }
}


function formatLatency(value) {

    const number =
        Number(value);

    if (
        Number.isNaN(number)
    ) {

        return "—";
    }

    return `${number.toFixed(1)} ms`;
}


function verdictClass(verdict) {

    const value =
        String(
            verdict || ""
        ).toLowerCase();

    if (value === "pass") {
        return "pass";
    }

    if (
        value === "drop" ||
        value === "alert" ||
        value === "blocked"
    ) {
        return "drop";
    }

    return "unknown";
}


function safe(value) {

    if (
        value === undefined ||
        value === null ||
        value === ""
    ) {

        return "—";
    }

    return String(value)
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


// =========================================================
// ATTACK PANEL
// =========================================================

function toggleAttackPanel() {

    const panel =
        document.getElementById(
            "attack-panel"
        );

    if (!panel) {
        return;
    }

    if (
        panel.style.display === "none" ||
        panel.style.display === ""
    ) {

        panel.style.display =
            "block";

    } else {

        panel.style.display =
            "none";
    }
}


// =========================================================
// TRIGGER ATTACK
// =========================================================

async function triggerAttack(attack) {

    try {

        const response =
            await fetch(
                "/api/trigger-attack",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        attack: attack
                    })
                }
            );

        const result =
            await response.json();

        console.log(
            "Attack:",
            result
        );

        if (!result.success) {

            console.error(
                "Attack rejected:",
                result.error
            );

            return;
        }

        console.log(
            `[DASHBOARD] ${attack} launched`
        );

    } catch (error) {

        console.error(
            "Attack failed:",
            error
        );
    }
}


// =========================================================
// RESET
// =========================================================

async function resetDashboard() {

    try {

        const response =
            await fetch(
                "/api/reset",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    }
                }
            );

        const result =
            await response.json();

        if (!result.success) {

            console.error(
                "Reset failed:",
                result.error
            );

            return;
        }

        console.log(
            "[DASHBOARD] Reset successful"
        );

        await refreshDashboard();

    } catch (error) {

        console.error(
            "Reset failed:",
            error
        );
    }
}


// =========================================================
// BUTTON EVENTS
// =========================================================

function setupButtons() {

    const attackButton =
        document.getElementById(
            "btn-trigger-attack"
        );

    const resetButton =
        document.getElementById(
            "btn-reset-data"
        );

    if (attackButton) {

        attackButton.addEventListener(
            "click",
            toggleAttackPanel
        );
    }

    if (resetButton) {

        resetButton.addEventListener(
            "click",
            resetDashboard
        );
    }
}


// =========================================================
// START
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    () => {

        setupButtons();

        refreshDashboard();

        setInterval(
            refreshDashboard,
            1000
        );
    }
);