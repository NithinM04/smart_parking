from functools import wraps

from flask import Flask, jsonify, render_template, request, redirect, url_for, session

import psycopg
from psycopg.rows import dict_row

import os

from dotenv import load_dotenv

from werkzeug.security import check_password_hash



load_dotenv()

from customer_portal import register_customer_portal

app = Flask(__name__)



# ============================================================

# Flask Session Configuration

# ============================================================



app.secret_key = os.getenv(

    "FLASK_SECRET_KEY",

    "CHANGE_THIS_SECRET_KEY"

)



app.config.update(

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=False,  # Change to True when using HTTPS

    PERMANENT_SESSION_LIFETIME=3600

)





# ============================================================

# PostgreSQL / Neon Configuration

# ============================================================



DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing. Add your Neon PostgreSQL connection string "
        "to the local .env file or deployment environment."
    )


# ============================================================
# Database Connection
# ============================================================


def get_db_connection():
    """Open a PostgreSQL connection to Neon using dictionary-like rows."""
    return psycopg.connect(
        DATABASE_URL,
        sslmode="require",
        row_factory=dict_row,
        connect_timeout=10,
    )


# Register the customer portal and Razorpay routes.
register_customer_portal(app, get_db_connection)










# ============================================================

# Convert PostgreSQL datetime values to JSON-safe strings

# ============================================================



def convert_datetime_rows(rows):



    for row in rows:



        for key, value in row.items():



            if hasattr(value, "strftime"):



                row[key] = value.strftime(

                    "%Y-%m-%d %H:%M:%S"

                )



    return rows





# ============================================================

# Client IP

# ============================================================



def get_client_ip():



    return request.remote_addr or "UNKNOWN"





# ============================================================

# Update Login Activity

# ============================================================



def update_login_activity():



    login_id = session.get("login_history_id")



    if not login_id:

        return



    conn = None

    cursor = None



    try:



        conn = get_db_connection()



        cursor = conn.cursor()



        cursor.execute(

            """

            UPDATE login_history

            SET last_activity = CURRENT_TIMESTAMP

            WHERE id = %s

            AND status = 'ACTIVE'

            """,

            (login_id,)

        )



        conn.commit()



    except psycopg.Error as e:



        print("[LOGIN ACTIVITY ERROR]", e)



    finally:



        if cursor:

            cursor.close()



        if conn and not conn.closed:

            conn.close()





# ============================================================

# Login Required Decorator

# ============================================================



def login_required(route_function):



    @wraps(route_function)

    def decorated_function(*args, **kwargs):



        if not session.get("authenticated"):



            if request.path.startswith("/api/"):



                return jsonify({

                    "status": "unauthorized",

                    "message": "Login required"

                }), 401



            return redirect(url_for("login"))



        update_login_activity()



        return route_function(*args, **kwargs)



    return decorated_function





# ============================================================

# Admin Required Decorator

# ============================================================



def admin_required(route_function):



    @wraps(route_function)

    def decorated_function(*args, **kwargs):



        if not session.get("authenticated"):



            if request.path.startswith("/api/"):



                return jsonify({

                    "status": "unauthorized",

                    "message": "Login required"

                }), 401



            return redirect(url_for("login"))



        if session.get("role") != "ADMIN":



            return jsonify({

                "status": "forbidden",

                "message": "Administrator access required"

            }), 403



        update_login_activity()



        return route_function(*args, **kwargs)



    return decorated_function





# ============================================================

# LOGIN

# ============================================================



@app.route("/login", methods=["GET", "POST"])
def login():
    """Single GUPIO login for Admin and Customer accounts."""

    
    if request.method == "GET":
        if session.get("customer_id"):
            return redirect(url_for("customer.customer_dashboard"))

        if session.get("authenticated"):
            return redirect(url_for("dashboard"))


    error = None
    selected_role = request.form.get("account_type", "admin").strip().lower()
    identity = request.form.get("identity", "").strip()
    password = request.form.get("password", "")

    if request.method == "POST":
        if selected_role not in ("admin", "customer"):
            error = "Please select a valid account type."
        elif not identity or not password:
            error = "Please enter your login details."
        else:
            conn = None
            cursor = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(row_factory=dict_row)

                if selected_role == "customer":
                    cursor.execute(
                        """SELECT id, full_name, email, password_hash, status
                           FROM customers WHERE email = %s LIMIT 1""",
                        (identity.lower(),),
                    )
                    customer = cursor.fetchone()

                    if (
                        customer
                        and customer["status"] == "ACTIVE"
                        and check_password_hash(customer["password_hash"], password)
                    ):
                        session.clear()
                        session.permanent = True
                        session["customer_id"] = customer["id"]
                        session["customer_name"] = customer["full_name"]
                        session["role"] = "CUSTOMER"
                        return redirect(url_for("customer.customer_dashboard"))

                    error = "Invalid customer email or password."

                else:
                    cursor.execute(
                        """SELECT id, username, password_hash, full_name, role, status
                           FROM dashboard_users WHERE username = %s LIMIT 1""",
                        (identity,),
                    )
                    user = cursor.fetchone()

                    if (
                        user
                        and user["status"] == "ACTIVE"
                        and user["role"] == "ADMIN"
                        and check_password_hash(user["password_hash"], password)
                    ):
                        cursor.execute(
                            """INSERT INTO login_history
                               (user_id, username, login_time, last_activity,
                                ip_address, user_agent, status)
                               VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                                       %s, %s, 'ACTIVE')
                               RETURNING id""",
                            (
                                user["id"],
                                user["username"],
                                get_client_ip(),
                                request.headers.get("User-Agent", "")[:500],
                            ),
                        )
                        login_history_id = cursor.fetchone()["id"]
                        conn.commit()

                        session.clear()
                        session.permanent = True
                        session["authenticated"] = True
                        session["user_id"] = user["id"]
                        session["username"] = user["username"]
                        session["full_name"] = user["full_name"]
                        session["role"] = "ADMIN"
                        session["login_history_id"] = login_history_id
                        return redirect(url_for("dashboard"))

                    error = "Invalid admin username or password."
                    cursor.execute(
                        """INSERT INTO login_history
                           (user_id, username, login_time, last_activity,
                            ip_address, user_agent, status)
                           VALUES (NULL, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                                   %s, %s, 'FAILED')""",
                        (
                            identity[:100],
                            get_client_ip(),
                            request.headers.get("User-Agent", "")[:500],
                        ),
                    )
                    conn.commit()

            except psycopg.Error as e:
                if conn:
                    conn.rollback()
                print("[POSTGRESQL LOGIN ERROR]", e)
                error = "Unable to connect to the authentication database."
            finally:
                if cursor:
                    cursor.close()
                if conn and not conn.closed:
                    conn.close()

    return render_template(
        "login.html",
        error=error,
        selected_role=selected_role,
        identity=identity,
    )


# ============================================================

# LOGOUT

# ============================================================



@app.route("/logout")

@login_required

def logout():



    login_history_id = session.get(

        "login_history_id"

    )



    conn = None

    cursor = None



    try:



        if login_history_id:



            conn = get_db_connection()



            cursor = conn.cursor()



            cursor.execute(

                """

                UPDATE login_history

                SET

                    logout_time = CURRENT_TIMESTAMP,

                    last_activity = CURRENT_TIMESTAMP,

                    status = 'LOGGED_OUT'

                WHERE id = %s

                """,

                (login_history_id,)

            )



            conn.commit()



    except psycopg.Error as e:



        print(

            "[LOGOUT ERROR]",

            e

        )



    finally:



        if cursor:

            cursor.close()



        if conn and not conn.closed:

            conn.close()



    session.clear()



    return redirect(

        url_for("login")

    )





# ============================================================

# DASHBOARD

# ============================================================



@app.route("/")
def landing_page():

    return render_template(
        "index.html"
    )


@app.route("/dashboard")
@login_required
def dashboard():

    return render_template(
        "index.html",
        username=session.get(
            "username",
            ""
        ),

        full_name=session.get(
            "full_name",
            ""
        ),

        role=session.get(
            "role",
            ""
        )
    )




# ============================================================

# DASHBOARD STATISTICS

# ============================================================



@app.route("/api/stats")
@login_required
def stats():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("SELECT COUNT(*) AS total_entries FROM parking_sessions")
        total_entries = cursor.fetchone()["total_entries"]
        cursor.execute("SELECT COUNT(*) AS currently_parked FROM parking_sessions WHERE status = 'PARKED'")
        currently_parked = cursor.fetchone()["currently_parked"]
        cursor.execute("SELECT COUNT(*) AS today_entries FROM parking_sessions WHERE entry_time::date = CURRENT_DATE")
        today_entries = cursor.fetchone()["today_entries"]
        cursor.execute("SELECT COUNT(*) AS allowed FROM access_logs WHERE result = 'ALLOWED'")
        allowed = cursor.fetchone()["allowed"]
        cursor.execute("SELECT COUNT(*) AS denied FROM access_logs WHERE result = 'DENIED'")
        denied = cursor.fetchone()["denied"]
        cursor.execute("SELECT COUNT(*) AS total_registered FROM rfid_users WHERE status = 'ACTIVE'")
        total_registered = cursor.fetchone()["total_registered"]
        return jsonify({"total_entries": total_entries, "currently_parked": currently_parked, "today_entries": today_entries, "allowed": allowed, "denied": denied, "total_registered": total_registered})
    except psycopg.Error as e:
        print("[POSTGRESQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and not conn.closed: conn.close()


@app.route("/api/vehicles")
@login_required
def vehicles():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("""SELECT id, rfid_uid, vehicle_number, owner_name, entry_time, status FROM parking_sessions ORDER BY entry_time DESC, id DESC""")
        vehicles = convert_datetime_rows(cursor.fetchall())
        return jsonify(vehicles)
    except psycopg.Error as e:
        print("[POSTGRESQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and not conn.closed: conn.close()


@app.route("/api/recent")
@login_required
def recent():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("""SELECT id, rfid_uid, vehicle_number, owner_name, entry_time, status FROM parking_sessions ORDER BY id DESC LIMIT 50""")
        recent_activity = convert_datetime_rows(cursor.fetchall())
        return jsonify(recent_activity)
    except psycopg.Error as e:
        print("[POSTGRESQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and not conn.closed: conn.close()




@app.route("/api/customer-vehicles")
@admin_required
def admin_customer_vehicles():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute(
            """SELECT cv.id, cv.customer_id, c.full_name, c.email,
                      cv.vehicle_number, cv.nickname, cv.created_at, cv.is_active,
                      COALESCE((
                        SELECT vrp.status FROM vehicle_registration_payments vrp
                        WHERE vrp.vehicle_id = cv.id AND vrp.customer_id = cv.customer_id
                        ORDER BY vrp.id DESC LIMIT 1
                      ), 'PENDING') AS payment_status
               FROM customer_vehicles cv
               JOIN customers c ON c.id = cv.customer_id
               ORDER BY cv.created_at DESC, cv.id DESC"""
        )
        return jsonify(convert_datetime_rows(cursor.fetchall()))
    except psycopg.Error as e:
        app.logger.exception("Admin customer vehicle list failed")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and not conn.closed: conn.close()


@app.route("/api/admin-payments")
@admin_required
def admin_payment_history():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute(
            """SELECT * FROM (
                 SELECT 'VEHICLE REGISTRATION' AS payment_type, vrp.id,
                        c.full_name AS customer_name, c.email,
                        cv.vehicle_number, vrp.amount_paise, vrp.currency,
                        vrp.status, vrp.razorpay_payment_id, vrp.created_at,
                        vrr.receipt_number
                 FROM vehicle_registration_payments vrp
                 JOIN customers c ON c.id = vrp.customer_id
                 JOIN customer_vehicles cv ON cv.id = vrp.vehicle_id
                 LEFT JOIN vehicle_registration_receipts vrr ON vrr.payment_id = vrp.id
                 UNION ALL
                 SELECT 'PARKING SESSION' AS payment_type, p.id,
                        c.full_name AS customer_name, c.email,
                        ps.vehicle_number, p.amount_paise, p.currency,
                        p.status, p.razorpay_payment_id, p.created_at,
                        r.receipt_number
                 FROM payments p
                 JOIN customers c ON c.id = p.customer_id
                 LEFT JOIN parking_sessions ps ON ps.id = p.parking_session_id
                 LEFT JOIN receipts r ON r.payment_id = p.id
               ) AS all_payments
               ORDER BY created_at DESC, id DESC LIMIT 500"""
        )
        return jsonify(convert_datetime_rows(cursor.fetchall()))
    except psycopg.Error as e:
        app.logger.exception("Admin payment history failed")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and not conn.closed: conn.close()


@app.route("/api/access")

@login_required

def access_logs():



    conn = None

    cursor = None



    try:



        conn = get_db_connection()



        cursor = conn.cursor(row_factory=dict_row)



        cursor.execute(

            """

            SELECT

                id,

                rfid_uid,

                result,

                timestamp

            FROM access_logs

            ORDER BY id DESC

            LIMIT 20

            """

        )



        logs = cursor.fetchall()



        logs = convert_datetime_rows(

            logs

        )



        return jsonify(

            logs

        )



    except psycopg.Error as e:



        print(

            "[POSTGRESQL ERROR]",

            e

        )



        return jsonify({



            "status": "error",



            "message": str(e)



        }), 500



    finally:



        if cursor:

            cursor.close()



        if conn and not conn.closed:

            conn.close()





# ============================================================

# LOGIN ACTIVITY

# ============================================================



@app.route("/api/login_activity")

@admin_required

def login_activity():



    conn = None

    cursor = None



    try:



        conn = get_db_connection()



        cursor = conn.cursor(row_factory=dict_row)



        cursor.execute(

            """

            SELECT

                id,

                username,

                login_time,

                logout_time,

                last_activity,

                ip_address,

                status

            FROM login_history

            ORDER BY id DESC

            LIMIT 50

            """

        )



        activity = cursor.fetchall()



        activity = convert_datetime_rows(

            activity

        )



        return jsonify(

            activity

        )



    except psycopg.Error as e:



        print(

            "[POSTGRESQL LOGIN ACTIVITY ERROR]",

            e

        )



        return jsonify({



            "status": "error",



            "message": str(e)



        }), 500



    finally:



        if cursor:

            cursor.close()



        if conn and not conn.closed:

            conn.close()





# ============================================================

# CURRENT USER

# ============================================================



@app.route("/api/current_user")

@login_required

def current_user():



    return jsonify({



        "username":

            session.get(

                "username",

                ""

            ),



        "full_name":

            session.get(

                "full_name",

                ""

            ),



        "role":

            session.get(

                "role",

                ""

            )



    })





# ============================================================

# RUN FLASK

# ============================================================



if __name__ == "__main__":



    print(

        "=============================================="

    )



    print(

        " SMART PARKING DASHBOARD"

    )



    print(

        "=============================================="

    )



    print(

        "Starting Flask server..."

    )



    print(

        "Login:     http://127.0.0.1:5000/login"

    )



    print(

        "Dashboard: http://127.0.0.1:5000/"

    )



    print(

        "=============================================="

    )



    app.run(

        host="127.0.0.1",

        port=5000,

        debug=True

    )