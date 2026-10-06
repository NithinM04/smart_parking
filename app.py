from flask import Flask, jsonify, render_template
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ============================================================
# MySQL Configuration
# ============================================================

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}


# ============================================================
# Database Connection
# ============================================================

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


# ============================================================
# Convert MySQL datetime values to JSON-safe strings
# ============================================================

def convert_datetime_rows(rows):
    for row in rows:
        for key, value in row.items():
            if hasattr(value, "strftime"):
                row[key] = value.strftime("%Y-%m-%d %H:%M:%S")

    return rows


# ============================================================
# Dashboard Page
# ============================================================

@app.route("/")
def dashboard():
    return render_template("index.html")


# ============================================================
# Dashboard Statistics
# ============================================================

@app.route("/api/stats")
def stats():

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # ----------------------------------------------------
        # Registered Vehicles
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total_registered
            FROM rfid_users
            WHERE status = 'ACTIVE'
        """)

        total_registered = cursor.fetchone()["total_registered"]

        # ----------------------------------------------------
        # Currently Parked
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS currently_parked
            FROM parking_sessions
            WHERE status = 'PARKED'
        """)

        currently_parked = cursor.fetchone()["currently_parked"]

        # ----------------------------------------------------
        # Today's IN
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS today_in
            FROM parking_sessions
            WHERE DATE(entry_time) = CURDATE()
        """)

        today_in = cursor.fetchone()["today_in"]

        # ----------------------------------------------------
        # Today's OUT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS today_out
            FROM parking_sessions
            WHERE exit_time IS NOT NULL
            AND DATE(exit_time) = CURDATE()
        """)

        today_out = cursor.fetchone()["today_out"]

        # ----------------------------------------------------
        # Authorized RFID Attempts Today
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS authorized
            FROM access_logs
            WHERE result = 'ALLOWED'
            AND DATE(timestamp) = CURDATE()
        """)

        authorized = cursor.fetchone()["authorized"]

        # ----------------------------------------------------
        # Denied RFID Attempts Today
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS denied
            FROM access_logs
            WHERE result = 'DENIED'
            AND DATE(timestamp) = CURDATE()
        """)

        denied = cursor.fetchone()["denied"]

        return jsonify({
            "total_registered": total_registered,
            "currently_parked": currently_parked,
            "today_in": today_in,
            "today_out": today_out,
            "authorized": authorized,
            "denied": denied
        })

    except mysql.connector.Error as e:

        print("[MYSQL ERROR]", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn and conn.is_connected():
            conn.close()


# ============================================================
# Currently Parked Vehicles
# ============================================================

@app.route("/api/vehicles")
def vehicles():

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                rfid_uid,
                vehicle_number,
                owner_name,
                entry_time,
                status
            FROM parking_sessions
            WHERE status = 'PARKED'
            ORDER BY entry_time DESC
        """)

        vehicles = cursor.fetchall()

        vehicles = convert_datetime_rows(vehicles)

        return jsonify(vehicles)

    except mysql.connector.Error as e:

        print("[MYSQL ERROR]", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn and conn.is_connected():
            conn.close()


# ============================================================
# Recent Parking Activity
# ============================================================

@app.route("/api/recent")
def recent():

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                rfid_uid,
                vehicle_number,
                owner_name,
                entry_time,
                exit_time,
                status
            FROM parking_sessions
            ORDER BY id DESC
            LIMIT 20
        """)

        recent_activity = cursor.fetchall()

        recent_activity = convert_datetime_rows(recent_activity)

        return jsonify(recent_activity)

    except mysql.connector.Error as e:

        print("[MYSQL ERROR]", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn and conn.is_connected():
            conn.close()


# ============================================================
# RFID Access Logs
# ============================================================

@app.route("/api/access")
def access_logs():

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                rfid_uid,
                result,
                timestamp
            FROM access_logs
            ORDER BY id DESC
            LIMIT 20
        """)

        logs = cursor.fetchall()

        logs = convert_datetime_rows(logs)

        return jsonify(logs)

    except mysql.connector.Error as e:

        print("[MYSQL ERROR]", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn and conn.is_connected():
            conn.close()


# ============================================================
# Run Flask Application
# ============================================================

if __name__ == "__main__":

    print("==============================================")
    print(" SMART PARKING DASHBOARD")
    print("==============================================")
    print("Starting Flask server...")
    print("Dashboard: http://127.0.0.1:5000")
    print("==============================================")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )