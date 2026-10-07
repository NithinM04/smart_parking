// ============================================================
// SMART PARKING DASHBOARD
// ENTRY-ONLY VERSION
// ============================================================


// ============================================================
// LOAD DASHBOARD
// ============================================================

async function loadDashboard() {

    try {

        // ------------------------------------------------------
        // STATISTICS
        // ------------------------------------------------------

        const statsResponse =
            await fetch("/api/stats");


        if (statsResponse.status === 401) {

            window.location.href = "/login";

            return;

        }


        if (!statsResponse.ok) {

            throw new Error(
                "Failed to load dashboard statistics"
            );

        }


        const stats =
            await statsResponse.json();


        if (stats.status === "error") {

            throw new Error(
                stats.message ||
                "Database error"
            );

        }


        // ------------------------------------------------------
        // TOTAL VEHICLES
        // ------------------------------------------------------

        const totalVehiclesElement =
            document.getElementById(
                "totalVehicles"
            );


        if (totalVehiclesElement) {

            totalVehiclesElement.textContent =
                stats.total_vehicles ?? 0;

        }


        // ------------------------------------------------------
        // REGISTERED VEHICLES
        // ------------------------------------------------------

        const totalRegisteredElement =
            document.getElementById(
                "totalRegistered"
            );


        if (totalRegisteredElement) {

            totalRegisteredElement.textContent =
                stats.total_registered ?? 0;

        }


        // ------------------------------------------------------
        // CURRENTLY PARKED
        // ------------------------------------------------------

        const currentlyParkedElement =
            document.getElementById(
                "currentlyParked"
            );


        if (currentlyParkedElement) {

            currentlyParkedElement.textContent =
                stats.currently_parked ?? 0;

        }


        // ------------------------------------------------------
        // TODAY'S ENTRIES
        // ------------------------------------------------------

        const todayInElement =
            document.getElementById(
                "todayIn"
            );


        if (todayInElement) {

            todayInElement.textContent =
                stats.today_in ?? 0;

        }


        // ------------------------------------------------------
        // ACCESS ALLOWED
        // ------------------------------------------------------

        const authorizedElement =
            document.getElementById(
                "authorized"
            );


        if (authorizedElement) {

            authorizedElement.textContent =
                stats.authorized ?? 0;

        }


        // ------------------------------------------------------
        // ACCESS DENIED
        // ------------------------------------------------------

        const deniedElement =
            document.getElementById(
                "denied"
            );


        if (deniedElement) {

            deniedElement.textContent =
                stats.denied ?? 0;

        }


        // ------------------------------------------------------
        // PARKING COUNT
        // ------------------------------------------------------

        const parkedCount =
            stats.currently_parked ?? 0;


        const parkingCountElement =
            document.getElementById(
                "parkingCount"
            );


        if (parkingCountElement) {

            parkingCountElement.textContent =
                `${parkedCount} Vehicle${parkedCount === 1 ? "" : "s"}`;

        }


        // ------------------------------------------------------
        // PARKED VEHICLES
        // ------------------------------------------------------

        await loadVehicles();


        // ------------------------------------------------------
        // RECENT ENTRY ACTIVITY
        // ------------------------------------------------------

        await loadRecentEntries();


        // ------------------------------------------------------
        // LAST UPDATED
        // ------------------------------------------------------

        const lastUpdated =
            document.getElementById(
                "lastUpdated"
            );


        if (lastUpdated) {

            lastUpdated.textContent =
                "Updated " +
                new Date().toLocaleTimeString();

        }


        updateSystemStatus(true);


    }

    catch (error) {

        console.error(
            "Dashboard error:",
            error
        );


        const lastUpdated =
            document.getElementById(
                "lastUpdated"
            );


        if (lastUpdated) {

            lastUpdated.textContent =
                "Connection error";

        }


        updateSystemStatus(false);

    }

}


// ============================================================
// LOAD PARKED VEHICLES
// ============================================================

async function loadVehicles() {

    const vehicleTable =
        document.getElementById(
            "vehiclesTable"
        );


    if (!vehicleTable) {

        return;

    }


    try {

        const response =
            await fetch("/api/vehicles");


        if (response.status === 401) {

            window.location.href = "/login";

            return;

        }


        if (!response.ok) {

            throw new Error(
                "Failed to load vehicles"
            );

        }


        const vehicles =
            await response.json();


        if (!Array.isArray(vehicles)) {

            throw new Error(
                "Invalid vehicle data received"
            );

        }


        vehicleTable.innerHTML = "";


        if (vehicles.length === 0) {

            vehicleTable.innerHTML = `

                <tr>

                    <td
                        colspan="5"
                        class="empty-row"
                    >

                        No vehicles are currently parked.

                    </td>

                </tr>

            `;

            return;

        }


        vehicles.forEach(vehicle => {

            vehicleTable.innerHTML += `

                <tr>

                    <td>

                        <strong>

                            ${escapeHTML(
                                vehicle.vehicle_number ||
                                "Unknown"
                            )}

                        </strong>

                    </td>


                    <td>

                        ${escapeHTML(
                            vehicle.owner_name ||
                            "Unknown"
                        )}

                    </td>


                    <td>

                        ${escapeHTML(
                            vehicle.rfid_uid ||
                            "-"
                        )}

                    </td>


                    <td>

                        ${formatDate(
                            vehicle.entry_time
                        )}

                    </td>


                    <td>

                        <span
                            class="status-badge status-parked"
                        >

                            ${escapeHTML(
                                vehicle.status ||
                                "PARKED"
                            )}

                        </span>

                    </td>

                </tr>

            `;

        });


    }

    catch (error) {

        console.error(
            "Vehicle loading error:",
            error
        );


        vehicleTable.innerHTML = `

            <tr>

                <td
                    colspan="5"
                    class="empty-row"
                >

                    Unable to load vehicle records.

                </td>

            </tr>

        `;

    }

}


// ============================================================
// LOAD RECENT ENTRY RECORDS
// ============================================================

async function loadRecentEntries() {

    const recentTable =
        document.getElementById(
            "recentTable"
        );


    const activityCount =
        document.getElementById(
            "activityCount"
        );


    if (!recentTable) {

        return;

    }


    try {

        const response =
            await fetch("/api/recent");


        if (response.status === 401) {

            window.location.href = "/login";

            return;

        }


        if (!response.ok) {

            throw new Error(
                "Failed to load recent entries"
            );

        }


        const recent =
            await response.json();


        if (!Array.isArray(recent)) {

            throw new Error(
                "Invalid recent entry data"
            );

        }


        recentTable.innerHTML = "";


        if (activityCount) {

            activityCount.textContent =
                `${recent.length} Record${recent.length === 1 ? "" : "s"}`;

        }


        if (recent.length === 0) {

            recentTable.innerHTML = `

                <tr>

                    <td
                        colspan="5"
                        class="empty-row"
                    >

                        No vehicle entries recorded yet.

                    </td>

                </tr>

            `;

            return;

        }


        recent.forEach(item => {

            recentTable.innerHTML += `

                <tr>

                    <td>

                        <strong>

                            ${escapeHTML(
                                item.vehicle_number ||
                                "Unknown"
                            )}

                        </strong>

                    </td>


                    <td>

                        ${escapeHTML(
                            item.owner_name ||
                            "Unknown"
                        )}

                    </td>


                    <td>

                        ${escapeHTML(
                            item.rfid_uid ||
                            "-"
                        )}

                    </td>


                    <td>

                        ${formatDate(
                            item.entry_time
                        )}

                    </td>


                    <td>

                        <span
                            class="status-badge status-parked"
                        >

                            ${escapeHTML(
                                item.status ||
                                "PARKED"
                            )}

                        </span>

                    </td>

                </tr>

            `;

        });


    }

    catch (error) {

        console.error(
            "Recent entries error:",
            error
        );


        if (activityCount) {

            activityCount.textContent =
                "Error";

        }


        recentTable.innerHTML = `

            <tr>

                <td
                    colspan="5"
                    class="empty-row"
                >

                    Unable to load recent entry activity.

                </td>

            </tr>

        `;

    }

}


// ============================================================
// RFID ACCESS LOGS
// ============================================================

async function loadAccessLogs() {

    const table =
        document.getElementById(
            "accessTable"
        );


    const count =
        document.getElementById(
            "accessCount"
        );


    if (!table) {

        return;

    }


    try {

        const response =
            await fetch("/api/access");


        if (response.status === 401) {

            window.location.href = "/login";

            return;

        }


        if (!response.ok) {

            throw new Error(
                "Failed to load RFID logs"
            );

        }


        const logs =
            await response.json();


        table.innerHTML = "";


        if (
            !Array.isArray(logs) ||
            logs.length === 0
        ) {

            if (count) {

                count.textContent =
                    "0 Records";

            }


            table.innerHTML = `

                <tr>

                    <td
                        colspan="3"
                        class="empty-row"
                    >

                        No RFID access records found.

                    </td>

                </tr>

            `;

            return;

        }


        if (count) {

            count.textContent =
                `${logs.length} Record${logs.length === 1 ? "" : "s"}`;

        }


        logs.forEach(log => {

            const resultClass =
                log.result === "ALLOWED"
                    ? "status-allowed"
                    : "status-denied";


            table.innerHTML += `

                <tr>

                    <td>

                        ${escapeHTML(
                            log.rfid_uid ||
                            "-"
                        )}

                    </td>


                    <td>

                        <span
                            class="status-badge ${resultClass}"
                        >

                            ${escapeHTML(
                                log.result ||
                                "UNKNOWN"
                            )}

                        </span>

                    </td>


                    <td>

                        ${formatDate(
                            log.timestamp
                        )}

                    </td>

                </tr>

            `;

        });


    }

    catch (error) {

        console.error(
            "RFID access error:",
            error
        );


        if (count) {

            count.textContent =
                "Error";

        }


        table.innerHTML = `

            <tr>

                <td
                    colspan="3"
                    class="empty-row"
                >

                    Unable to load RFID access activity.

                </td>

            </tr>

        `;

    }

}


// ============================================================
// LOGIN ACTIVITY
// ============================================================

async function loadLoginActivity() {

    const table =
        document.getElementById(
            "loginActivityTable"
        );


    const count =
        document.getElementById(
            "loginActivityCount"
        );


    if (!table) {

        return;

    }


    try {

        const response =
            await fetch(
                "/api/login_activity"
            );


        if (response.status === 401) {

            window.location.href = "/login";

            return;

        }


        if (response.status === 403) {

            if (count) {

                count.textContent =
                    "Admin Only";

            }


            table.innerHTML = `

                <tr>

                    <td
                        colspan="6"
                        class="empty-row"
                    >

                        Administrator access is required.

                    </td>

                </tr>

            `;

            return;

        }


        if (!response.ok) {

            throw new Error(
                "Failed to load login activity"
            );

        }


        const records =
            await response.json();


        table.innerHTML = "";


        if (
            !Array.isArray(records) ||
            records.length === 0
        ) {

            if (count) {

                count.textContent =
                    "0 Records";

            }


            table.innerHTML = `

                <tr>

                    <td
                        colspan="6"
                        class="empty-row"
                    >

                        No login activity recorded.

                    </td>

                </tr>

            `;

            return;

        }


        if (count) {

            count.textContent =
                `${records.length} Record${records.length === 1 ? "" : "s"}`;

        }


        records.forEach(record => {

            let statusClass =
                "status-denied";


            if (
                record.status === "ACTIVE"
            ) {

                statusClass =
                    "status-active";

            }

            else if (
                record.status === "LOGGED_OUT"
            ) {

                statusClass =
                    "status-parked";

            }

            else if (
                record.status === "FAILED"
            ) {

                statusClass =
                    "status-denied";

            }


            table.innerHTML += `

                <tr>

                    <td>

                        <strong>

                            ${escapeHTML(
                                record.username ||
                                "UNKNOWN"
                            )}

                        </strong>

                    </td>


                    <td>

                        ${formatDate(
                            record.login_time
                        )}

                    </td>


                    <td>

                        ${formatDate(
                            record.last_activity
                        )}

                    </td>


                    <td>

                        ${formatDate(
                            record.logout_time
                        )}

                    </td>


                    <td>

                        ${escapeHTML(
                            record.ip_address ||
                            "-"
                        )}

                    </td>


                    <td>

                        <span
                            class="status-badge ${statusClass}"
                        >

                            ${escapeHTML(
                                record.status ||
                                "UNKNOWN"
                            )}

                        </span>

                    </td>

                </tr>

            `;

        });


    }

    catch (error) {

        console.error(
            "Login activity error:",
            error
        );


        table.innerHTML = `

            <tr>

                <td
                    colspan="6"
                    class="empty-row"
                >

                    Unable to load login activity.

                </td>

            </tr>

        `;

    }

}


// ============================================================
// DATE FORMAT
// ============================================================

function formatDate(dateString) {

    if (!dateString) {

        return "-";

    }


    try {

        const date =
            new Date(dateString);


        if (
            isNaN(
                date.getTime()
            )
        ) {

            return escapeHTML(
                dateString
            );

        }


        return date.toLocaleString();

    }

    catch (error) {

        console.error(
            "Date formatting error:",
            error
        );


        return escapeHTML(
            dateString
        );

    }

}


// ============================================================
// HTML ESCAPE
// ============================================================

function escapeHTML(value) {

    if (
        value === null ||
        value === undefined
    ) {

        return "";

    }


    return String(value)

        .replace(
            /&/g,
            "&amp;"
        )

        .replace(
            /</g,
            "&lt;"
        )

        .replace(
            />/g,
            "&gt;"
        )

        .replace(
            /"/g,
            "&quot;"
        )

        .replace(
            /'/g,
            "&#039;"
        );

}


// ============================================================
// SYSTEM STATUS
// ============================================================

function updateSystemStatus(online) {

    const systemStatus =
        document.querySelector(
            ".system-status"
        );


    if (!systemStatus) {

        return;

    }


    const statusStrong =
        systemStatus.querySelector(
            "strong"
        );


    const statusSmall =
        systemStatus.querySelector(
            "small"
        );


    const statusDot =
        systemStatus.querySelector(
            ".status-dot"
        );


    const dashboardStatus =
        document.getElementById(
            "systemStatus"
        );


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


        if (dashboardStatus) {

            dashboardStatus.textContent =
                "Online";

            dashboardStatus.classList.add(
                "online-text"
            );

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


        if (dashboardStatus) {

            dashboardStatus.textContent =
                "Offline";

            dashboardStatus.classList.remove(
                "online-text"
            );

        }

    }

}


// ============================================================
// NAVIGATION
// ============================================================

function setupNavigation() {

    const navItems =
        document.querySelectorAll(
            ".nav-item"
        );


    const dashboardView =
        document.getElementById(
            "dashboardView"
        );


    const accessView =
        document.getElementById(
            "access"
        );


    const loginActivityView =
        document.getElementById(
            "login-activity"
        );


    const pageTitle =
        document.getElementById(
            "pageTitle"
        );


    const pageSubtitle =
        document.getElementById(
            "pageSubtitle"
        );


    function showSection(section) {

        // ------------------------------------------------------
        // HIDE SPECIAL SECTIONS
        // ------------------------------------------------------

        if (accessView) {

            accessView.classList.add(
                "hidden-view"
            );

        }


        if (loginActivityView) {

            loginActivityView.classList.add(
                "hidden-view"
            );

        }


        // ------------------------------------------------------
        // DASHBOARD / PARKING / ACTIVITY
        // ------------------------------------------------------

        if (
            section === "dashboard" ||
            section === "parking" ||
            section === "activity"
        ) {

            if (dashboardView) {

                dashboardView.classList.remove(
                    "hidden-view"
                );

            }


            if (
                section === "dashboard"
            ) {

                if (pageTitle) {

                    pageTitle.textContent =
                        "Dashboard";

                }


                if (pageSubtitle) {

                    pageSubtitle.textContent =
                        "Smart Parking System Overview";

                }

            }


            else if (
                section === "parking"
            ) {

                if (pageTitle) {

                    pageTitle.textContent =
                        "Parking";

                }


                if (pageSubtitle) {

                    pageSubtitle.textContent =
                        "Currently parked vehicles";

                }


                const target =
                    document.getElementById(
                        "parking"
                    );


                if (target) {

                    setTimeout(
                        () => {

                            target.scrollIntoView({
                                behavior: "smooth",
                                block: "start"
                            });

                        },
                        50
                    );

                }

            }


            else {

                if (pageTitle) {

                    pageTitle.textContent =
                        "Activity";

                }


                if (pageSubtitle) {

                    pageSubtitle.textContent =
                        "Recent vehicle entries";

                }


                const target =
                    document.getElementById(
                        "activity"
                    );


                if (target) {

                    setTimeout(
                        () => {

                            target.scrollIntoView({
                                behavior: "smooth",
                                block: "start"
                            });

                        },
                        50
                    );

                }

            }

        }


        // ------------------------------------------------------
        // RFID ACCESS
        // ------------------------------------------------------

        else if (
            section === "access"
        ) {

            if (dashboardView) {

                dashboardView.classList.add(
                    "hidden-view"
                );

            }


            if (accessView) {

                accessView.classList.remove(
                    "hidden-view"
                );

            }


            if (pageTitle) {

                pageTitle.textContent =
                    "RFID Access";

            }


            if (pageSubtitle) {

                pageSubtitle.textContent =
                    "RFID authorization activity";

            }


            loadAccessLogs();

        }


        // ------------------------------------------------------
        // LOGIN ACTIVITY
        // ------------------------------------------------------

        else if (
            section === "login-activity"
        ) {

            if (dashboardView) {

                dashboardView.classList.add(
                    "hidden-view"
                );

            }


            if (loginActivityView) {

                loginActivityView.classList.remove(
                    "hidden-view"
                );

            }


            if (pageTitle) {

                pageTitle.textContent =
                    "Login Activity";

            }


            if (pageSubtitle) {

                pageSubtitle.textContent =
                    "Monitor dashboard login sessions";

            }


            loadLoginActivity();

        }

    }


    // ----------------------------------------------------------
    // NAVIGATION CLICK EVENTS
    // ----------------------------------------------------------

    navItems.forEach(item => {

        item.addEventListener(
            "click",
            function(event) {

                event.preventDefault();


                navItems.forEach(nav => {

                    nav.classList.remove(
                        "active"
                    );

                });


                this.classList.add(
                    "active"
                );


                const section =
                    this.dataset.section ||
                    "dashboard";


                showSection(
                    section
                );

            }
        );

    });

}


// ============================================================
// INITIALIZE
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    function() {

        loadDashboard();

        setupNavigation();

    }
);


// ============================================================
// AUTO REFRESH DASHBOARD
// ============================================================

setInterval(
    loadDashboard,
    5000
);


// ============================================================
// AUTO REFRESH RFID ACCESS
// ============================================================

setInterval(
    () => {

        const accessView =
            document.getElementById(
                "access"
            );


        if (
            accessView &&
            !accessView.classList.contains(
                "hidden-view"
            )
        ) {

            loadAccessLogs();

        }

    },
    5000
);


// ============================================================
// AUTO REFRESH LOGIN ACTIVITY
// ============================================================

setInterval(
    () => {

        const loginActivityView =
            document.getElementById(
                "login-activity"
            );


        if (
            loginActivityView &&
            !loginActivityView.classList.contains(
                "hidden-view"
            )
        ) {

            loadLoginActivity();

        }

    },
    5000
);