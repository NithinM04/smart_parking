// ============================================================
// SMART PARKING DASHBOARD
// ============================================================


// ============================================================
// LOAD DASHBOARD DATA
// ============================================================

async function loadDashboard() {

    try {

        // ====================================================
        // LOAD DASHBOARD STATISTICS
        // ====================================================

        const statsResponse = await fetch("/api/stats");

        if (!statsResponse.ok) {
            throw new Error("Failed to load dashboard statistics");
        }

        const stats = await statsResponse.json();

        // Check API error
        if (stats.status === "error") {
            throw new Error(stats.message || "Database error");
        }


        // ====================================================
        // UPDATE STATISTICS CARDS
        // ====================================================

        document.getElementById("totalRegistered").textContent =
            stats.total_registered ?? 0;

        document.getElementById("currentlyParked").textContent =
            stats.currently_parked ?? 0;

        document.getElementById("todayIn").textContent =
            stats.today_in ?? 0;

        document.getElementById("todayOut").textContent =
            stats.today_out ?? 0;

        document.getElementById("authorized").textContent =
            stats.authorized ?? 0;

        document.getElementById("denied").textContent =
            stats.denied ?? 0;


        // ====================================================
        // UPDATE CURRENT PARKING COUNT
        // ====================================================

        const parkedCount = stats.currently_parked ?? 0;

        document.getElementById("parkingCount").textContent =
            `${parkedCount} Vehicle${parkedCount === 1 ? "" : "s"}`;


        // ====================================================
        // LOAD CURRENTLY PARKED VEHICLES
        // ====================================================

        const vehiclesResponse = await fetch("/api/vehicles");

        if (!vehiclesResponse.ok) {
            throw new Error("Failed to load parked vehicles");
        }

        const vehicles = await vehiclesResponse.json();

        if (!Array.isArray(vehicles)) {
            throw new Error("Invalid vehicle data received");
        }


        const vehicleTable =
            document.getElementById("vehiclesTable");

        vehicleTable.innerHTML = "";


        // ====================================================
        // NO PARKED VEHICLES
        // ====================================================

        if (vehicles.length === 0) {

            vehicleTable.innerHTML = `
                <tr>
                    <td colspan="5" class="empty-row">
                        No vehicles are currently parked.
                    </td>
                </tr>
            `;

        }


        // ====================================================
        // DISPLAY PARKED VEHICLES
        // ====================================================

        else {

            vehicles.forEach(vehicle => {

                vehicleTable.innerHTML += `
                    <tr>

                        <td>
                            <strong>
                                ${escapeHTML(
                                    vehicle.vehicle_number || "Unknown"
                                )}
                            </strong>
                        </td>

                        <td>
                            ${escapeHTML(
                                vehicle.owner_name || "Unknown"
                            )}
                        </td>

                        <td>
                            ${escapeHTML(
                                vehicle.rfid_uid || "-"
                            )}
                        </td>

                        <td>
                            ${formatDate(vehicle.entry_time)}
                        </td>

                        <td>
                            <span class="status-badge status-parked">
                                PARKED
                            </span>
                        </td>

                    </tr>
                `;

            });

        }


        // ====================================================
        // LOAD RECENT PARKING ACTIVITY
        // ====================================================

        const recentResponse = await fetch("/api/recent");

        if (!recentResponse.ok) {
            throw new Error("Failed to load recent parking activity");
        }

        const recent = await recentResponse.json();

        if (!Array.isArray(recent)) {
            throw new Error("Invalid recent activity data received");
        }


        const recentTable =
            document.getElementById("recentTable");

        recentTable.innerHTML = "";


        // ====================================================
        // NO PARKING ACTIVITY
        // ====================================================

        if (recent.length === 0) {

            recentTable.innerHTML = `
                <tr>
                    <td colspan="6" class="empty-row">
                        No parking activity recorded yet.
                    </td>
                </tr>
            `;

        }


        // ====================================================
        // DISPLAY RECENT PARKING ACTIVITY
        // ====================================================

        else {

            recent.forEach(item => {

                let statusClass;

                if (item.status === "PARKED") {
                    statusClass = "status-parked";
                }
                else {
                    statusClass = "status-exited";
                }


                recentTable.innerHTML += `
                    <tr>

                        <td>
                            <strong>
                                ${escapeHTML(
                                    item.vehicle_number || "Unknown"
                                )}
                            </strong>
                        </td>

                        <td>
                            ${escapeHTML(
                                item.owner_name || "Unknown"
                            )}
                        </td>

                        <td>
                            ${escapeHTML(
                                item.rfid_uid || "-"
                            )}
                        </td>

                        <td>
                            ${formatDate(item.entry_time)}
                        </td>

                        <td>
                            ${
                                item.exit_time
                                    ? formatDate(item.exit_time)
                                    : "-"
                            }
                        </td>

                        <td>
                            <span class="status-badge ${statusClass}">
                                ${escapeHTML(
                                    item.status || "UNKNOWN"
                                )}
                            </span>
                        </td>

                    </tr>
                `;

            });

        }


        // ====================================================
        // UPDATE LAST UPDATED TIME
        // ====================================================

        const now = new Date();

        document.getElementById("lastUpdated").textContent =
            "Updated " + now.toLocaleTimeString();


        // ====================================================
        // SYSTEM STATUS
        // ====================================================

        updateSystemStatus(true);

    }


    // ========================================================
    // ERROR HANDLING
    // ========================================================

    catch (error) {

        console.error(
            "Dashboard error:",
            error
        );

        document.getElementById("lastUpdated").textContent =
            "Connection error";

        updateSystemStatus(false);

    }

}


// ============================================================
// DATE FORMATTER
// ============================================================

function formatDate(dateString) {

    if (!dateString) {
        return "-";
    }

    try {

        const date = new Date(dateString);

        if (isNaN(date.getTime())) {
            return dateString;
        }

        return date.toLocaleString();

    }

    catch (error) {

        console.error(
            "Date formatting error:",
            error
        );

        return dateString;
    }
}


// ============================================================
// HTML ESCAPE
// Prevents database values from being interpreted as HTML
// ============================================================

function escapeHTML(value) {

    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// ============================================================
// SYSTEM STATUS
// ============================================================

function updateSystemStatus(online) {

    const systemStatus =
        document.querySelector(".system-status");

    if (!systemStatus) {
        return;
    }


    const statusStrong =
        systemStatus.querySelector("strong");

    const statusSmall =
        systemStatus.querySelector("small");

    const statusDot =
        systemStatus.querySelector(".status-dot");


    if (online) {

        if (statusStrong) {
            statusStrong.textContent =
                "System Online";
        }

        if (statusSmall) {
            statusSmall.textContent =
                "MySQL Connected";
        }

        if (statusDot) {
            statusDot.style.background =
                "#22c55e";
        }

    }

    else {

        if (statusStrong) {
            statusStrong.textContent =
                "Connection Error";
        }

        if (statusSmall) {
            statusSmall.textContent =
                "Check Flask / MySQL";
        }

        if (statusDot) {
            statusDot.style.background =
                "#ef4444";
        }

    }

}


// ============================================================
// NAVIGATION
// ============================================================

function setupNavigation() {

    const navItems =
        document.querySelectorAll(".nav-item");


    navItems.forEach(item => {

        item.addEventListener("click", function () {

            navItems.forEach(nav => {
                nav.classList.remove("active");
            });

            this.classList.add("active");

        });

    });

}


// ============================================================
// INITIALIZE DASHBOARD
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    function () {

        // Load dashboard immediately
        loadDashboard();

        // Setup sidebar navigation
        setupNavigation();

    }
);


// ============================================================
// AUTO REFRESH
// Refresh dashboard every 5 seconds
// ============================================================

setInterval(
    loadDashboard,
    5000
);