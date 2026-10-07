from functools import wraps

from flask import Flask, jsonify, render_template, request, redirect, url_for, session

import mysql.connector

import os

from dotenv import load_dotenv

from werkzeug.security import check_password_hash



load_dotenv()



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



    except mysql.connector.Error as e:



        print("[LOGIN ACTIVITY ERROR]", e)



    finally:



        if cursor:

            cursor.close()



        if conn and conn.is_connected():

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



    if session.get("authenticated"):



        return redirect(url_for("dashboard"))



    error = None



    if request.method == "POST":



        username = request.form.get(

            "username",

            ""

        ).strip()



        password = request.form.get(

            "password",

            ""

        )



        if not username or not password:



            error = "Username and password are required."



            return render_template(

                "login.html",

                error=error

            )



        conn = None

        cursor = None



        try:



            conn = get_db_connection()



            cursor = conn.cursor(

                dictionary=True

            )



            cursor.execute(

                """

                SELECT

                    id,

                    username,

                    password_hash,

                    full_name,

                    role,

                    status

                FROM dashboard_users

                WHERE username = %s

                LIMIT 1

                """,

                (username,)

            )



            user = cursor.fetchone()



            # ====================================================

            # VALID LOGIN

            # ====================================================



            if (

                user

                and user["status"] == "ACTIVE"

                and check_password_hash(

                    user["password_hash"],

                    password

                )

            ):



                cursor.execute(

                    """

                    INSERT INTO login_history

                    (

                        user_id,

                        username,

                        login_time,

                        last_activity,

                        ip_address,

                        user_agent,

                        status

                    )

                    VALUES

                    (

                        %s,

                        %s,

                        CURRENT_TIMESTAMP,

                        CURRENT_TIMESTAMP,

                        %s,

                        %s,

                        'ACTIVE'

                    )

                    """,

                    (

                        user["id"],

                        user["username"],

                        get_client_ip(),

                        request.headers.get(

                            "User-Agent",

                            ""

                        )[:500]

                    )

                )



                login_history_id = cursor.lastrowid



                conn.commit()



                session.clear()



                session.permanent = True



                session["authenticated"] = True

                session["user_id"] = user["id"]

                session["username"] = user["username"]

                session["full_name"] = user["full_name"]

                session["role"] = user["role"]

                session["login_history_id"] = login_history_id



                return redirect(

                    url_for("dashboard")

                )



            # ====================================================

            # INVALID LOGIN

            # ====================================================



            error = "Invalid username or password."



            cursor.execute(

                """

                INSERT INTO login_history

                (

                    user_id,

                    username,

                    login_time,

                    last_activity,

                    ip_address,

                    user_agent,

                    status

                )

                VALUES

                (

                    NULL,

                    %s,

                    CURRENT_TIMESTAMP,

                    CURRENT_TIMESTAMP,

                    %s,

                    %s,

                    'FAILED'

                )

                """,

                (

                    username[:100],

                    get_client_ip(),

                    request.headers.get(

                        "User-Agent",

                        ""

                    )[:500]

                )

            )



            conn.commit()



        except mysql.connector.Error as e:



            print(

                "[MYSQL LOGIN ERROR]",

                e

            )



            error = (

                "Unable to connect to "

                "the authentication database."

            )



        finally:



            if cursor:

                cursor.close()



            if conn and conn.is_connected():

                conn.close()



    return render_template(

        "login.html",

        error=error

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



    except mysql.connector.Error as e:



        print(

            "[LOGOUT ERROR]",

            e

        )



    finally:



        if cursor:

            cursor.close()



        if conn and conn.is_connected():

            conn.close()



    session.clear()



    return redirect(

        url_for("login")

    )





# ============================================================

# DASHBOARD

# ============================================================



@app.route("/")

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
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS total_entries FROM parking_sessions")
        total_entries = cursor.fetchone()["total_entries"]
        cursor.execute("SELECT COUNT(*) AS currently_parked FROM parking_sessions WHERE status = 'PARKED'")
        currently_parked = cursor.fetchone()["currently_parked"]
        cursor.execute("SELECT COUNT(*) AS today_entries FROM parking_sessions WHERE DATE(entry_time) = CURDATE()")
        today_entries = cursor.fetchone()["today_entries"]
        cursor.execute("SELECT COUNT(*) AS allowed FROM access_logs WHERE result = 'ALLOWED'")
        allowed = cursor.fetchone()["allowed"]
        cursor.execute("SELECT COUNT(*) AS denied FROM access_logs WHERE result = 'DENIED'")
        denied = cursor.fetchone()["denied"]
        cursor.execute("SELECT COUNT(*) AS total_registered FROM rfid_users WHERE status = 'ACTIVE'")
        total_registered = cursor.fetchone()["total_registered"]
        return jsonify({"total_entries": total_entries, "currently_parked": currently_parked, "today_entries": today_entries, "allowed": allowed, "denied": denied, "total_registered": total_registered})
    except mysql.connector.Error as e:
        print("[MYSQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/api/vehicles")
@login_required
def vehicles():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT id, rfid_uid, vehicle_number, owner_name, entry_time, status FROM parking_sessions ORDER BY entry_time DESC, id DESC""")
        vehicles = convert_datetime_rows(cursor.fetchall())
        return jsonify(vehicles)
    except mysql.connector.Error as e:
        print("[MYSQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/api/recent")
@login_required
def recent():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT id, rfid_uid, vehicle_number, owner_name, entry_time, status FROM parking_sessions ORDER BY id DESC LIMIT 50""")
        recent_activity = convert_datetime_rows(cursor.fetchall())
        return jsonify(recent_activity)
    except mysql.connector.Error as e:
        print("[MYSQL ERROR]", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


@app.route("/api/access")

@login_required

def access_logs():



    conn = None

    cursor = None



    try:



        conn = get_db_connection()



        cursor = conn.cursor(

            dictionary=True

        )



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



    except mysql.connector.Error as e:



        print(

            "[MYSQL ERROR]",

            e

        )



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

# LOGIN ACTIVITY

# ============================================================



@app.route("/api/login_activity")

@admin_required

def login_activity():



    conn = None

    cursor = None



    try:



        conn = get_db_connection()



        cursor = conn.cursor(

            dictionary=True

        )



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



    except mysql.connector.Error as e:



        print(

            "[MYSQL LOGIN ACTIVITY ERROR]",

            e

        )



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