"""Customer portal and Razorpay integration for GUPIO Smart Parking.

This module is registered by app.py and uses the existing MySQL connection.
Razorpay secrets are read from server environment variables.
"""

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from functools import wraps

import mysql.connector
import razorpay
from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash


customer_bp = Blueprint("customer", __name__, url_prefix="/customer")
FIXED_FEE_RUPEES = int(os.getenv("PARKING_FIXED_FEE", "50"))
FIXED_FEE_PAISE = FIXED_FEE_RUPEES * 100


def _db():
    return current_app.config["GUPIO_DB_CONNECTOR"]()


def _razorpay_client():
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RuntimeError(
            "Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."
        )
    return razorpay.Client(auth=(key_id, key_secret))


def _csrf_token():
    token = session.get("customer_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["customer_csrf_token"] = token
    return token


@customer_bp.context_processor
def inject_customer_csrf():
    return {
        "customer_csrf_token": _csrf_token,
        "parking_fixed_fee": FIXED_FEE_RUPEES,
    }


@customer_bp.before_request
def protect_customer_posts():
    if request.method == "POST":
        supplied = (
            request.headers.get("X-CSRF-Token")
            or request.form.get("csrf_token")
        )
        expected = session.get("customer_csrf_token", "")
        if (
            not supplied
            or not expected
            or not hmac.compare_digest(str(supplied), str(expected))
        ):
            return jsonify({
                "status": "error",
                "message": "Your session token expired. Refresh the page and try again.",
            }), 400


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("customer_id"):
            return redirect(url_for("customer.customer_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _normalise_plate(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _customer_session(cursor, customer_id, parking_session_id, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute(
        """SELECT ps.id, ps.rfid_uid, ps.vehicle_number, ps.owner_name,
                  ps.entry_time, ps.exit_time, ps.status
           FROM parking_sessions ps
           INNER JOIN customer_vehicles cv
             ON REPLACE(REPLACE(UPPER(ps.vehicle_number), ' ', ''), '-', '') =
                cv.vehicle_number_normalized
           WHERE cv.customer_id = %s AND ps.id = %s
           LIMIT 1""" + suffix,
        (customer_id, parking_session_id),
    )
    return cursor.fetchone()


def _mark_payment_captured(cursor, payment_row, razorpay_payment_id):
    cursor.execute(
        """UPDATE payments
           SET razorpay_payment_id = %s, status = 'CAPTURED',
               captured_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
           WHERE id = %s AND status <> 'CAPTURED'""",
        (razorpay_payment_id, payment_row["id"]),
    )
    cursor.execute(
        "SELECT id FROM receipts WHERE payment_id = %s LIMIT 1",
        (payment_row["id"],),
    )
    if not cursor.fetchone():
        receipt_no = (
            "GUPIO-" + datetime.utcnow().strftime("%Y%m%d") + "-"
            + uuid.uuid4().hex[:8].upper()
        )
        cursor.execute(
            """INSERT INTO receipts (payment_id, receipt_number, issued_at)
               VALUES (%s, %s, CURRENT_TIMESTAMP)""",
            (payment_row["id"], receipt_no),
        )


@customer_bp.route("/register", methods=["GET", "POST"])
def customer_register():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if (
            not name or len(name) > 100
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or len(password) < 8
        ):
            flash(
                "Enter your name, a valid email and a password with at least 8 characters.",
                "error",
            )
            return render_template("customer_register.html"), 400

        conn = cursor = None
        try:
            conn = _db()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO customers
                   (full_name, email, phone, password_hash, status)
                   VALUES (%s, %s, %s, %s, 'ACTIVE')""",
                (name, email, phone or None, generate_password_hash(password)),
            )
            conn.commit()
            session["customer_id"] = cursor.lastrowid
            session["customer_name"] = name
            session.permanent = True
            flash("Your GUPIO customer account has been created.", "success")
            return redirect(url_for("customer.customer_dashboard"))
        except mysql.connector.IntegrityError:
            if conn:
                conn.rollback()
            flash("An account with this email already exists. Please sign in.", "error")
        except mysql.connector.Error:
            if conn:
                conn.rollback()
            current_app.logger.exception("Customer registration database error")
            flash("We could not create your account. Please try again.", "error")
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
    return render_template("customer_register.html")


@customer_bp.route("/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = cursor = None
        try:
            conn = _db()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """SELECT id, full_name, password_hash, status
                   FROM customers WHERE email = %s LIMIT 1""",
                (email,),
            )
            customer = cursor.fetchone()
            if (
                customer and customer["status"] == "ACTIVE"
                and check_password_hash(customer["password_hash"], password)
            ):
                session["customer_id"] = customer["id"]
                session["customer_name"] = customer["full_name"]
                session.permanent = True
                return redirect(url_for("customer.customer_dashboard"))
            flash("Invalid email or password.", "error")
        except mysql.connector.Error:
            current_app.logger.exception("Customer login database error")
            flash("Unable to sign in right now. Please try again.", "error")
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
    return render_template("customer_login.html")


@customer_bp.route("/logout", methods=["POST"])
@customer_required
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    session.pop("customer_csrf_token", None)
    return redirect(url_for("customer.customer_login"))


def _get_customer_payment_history(cursor, customer_id, limit=50):
    """Combine vehicle-registration and parking-session payments."""
    cursor.execute(
        """SELECT * FROM (
             SELECT 'VEHICLE REGISTRATION' AS payment_type,
                    vrp.id, cv.vehicle_number, NULL AS parking_session_id,
                    vrp.amount_paise, vrp.currency, vrp.status,
                    vrp.razorpay_payment_id, vrp.created_at,
                    vrr.receipt_number
             FROM vehicle_registration_payments vrp
             JOIN customer_vehicles cv ON cv.id = vrp.vehicle_id
             LEFT JOIN vehicle_registration_receipts vrr
                    ON vrr.payment_id = vrp.id
             WHERE vrp.customer_id = %s
             UNION ALL
             SELECT 'PARKING SESSION' AS payment_type,
                    p.id, ps.vehicle_number, p.parking_session_id,
                    p.amount_paise, p.currency, p.status,
                    p.razorpay_payment_id, p.created_at,
                    r.receipt_number
             FROM payments p
             LEFT JOIN parking_sessions ps ON ps.id = p.parking_session_id
             LEFT JOIN receipts r ON r.payment_id = p.id
             WHERE p.customer_id = %s
           ) AS combined_payments
           ORDER BY created_at DESC, id DESC LIMIT %s""",
        (customer_id, customer_id, limit),
    )
    rows = cursor.fetchall()
    for row in rows:
        if row.get("created_at"):
            row["created_at"] = row["created_at"].strftime("%d %b %Y, %I:%M %p")
    return rows


@customer_bp.route("/")
@customer_required
def customer_dashboard():
    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT cv.id, cv.vehicle_number, cv.nickname, cv.created_at,
                      (SELECT vrp.status FROM vehicle_registration_payments vrp
                       WHERE vrp.vehicle_id = cv.id AND vrp.customer_id = cv.customer_id
                       ORDER BY vrp.id DESC LIMIT 1) AS registration_payment_status,
                      (SELECT vrp.id FROM vehicle_registration_payments vrp
                       WHERE vrp.vehicle_id = cv.id AND vrp.customer_id = cv.customer_id
                       ORDER BY vrp.id DESC LIMIT 1) AS registration_payment_id
               FROM customer_vehicles cv
               WHERE cv.customer_id = %s AND cv.is_active = 1
               ORDER BY cv.id DESC""",
            (session["customer_id"],),
        )
        vehicles = cursor.fetchall()
        cursor.execute(
            """SELECT ps.id, ps.vehicle_number, ps.owner_name, ps.entry_time,
                      ps.status,
                      (SELECT p.status FROM payments p
                       WHERE p.parking_session_id = ps.id
                       ORDER BY p.id DESC LIMIT 1) AS payment_status
               FROM parking_sessions ps
               INNER JOIN customer_vehicles cv
                 ON REPLACE(REPLACE(UPPER(ps.vehicle_number), ' ', ''), '-', '') =
                    cv.vehicle_number_normalized
               WHERE cv.customer_id = %s AND cv.is_active = 1
                 AND ps.status = 'PARKED' AND ps.exit_time IS NULL
               ORDER BY ps.entry_time DESC""",
            (session["customer_id"],),
        )
        active_sessions = cursor.fetchall()
        payments = _get_customer_payment_history(cursor, session["customer_id"], 10)
        for rows in (vehicles, active_sessions):
            for row in rows:
                for key, value in row.items():
                    if hasattr(value, "strftime"):
                        row[key] = value.strftime("%d %b %Y, %I:%M %p")
        return render_template(
            "customer_dashboard.html",
            vehicles=vehicles,
            active_sessions=active_sessions,
            payments=payments,
            razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
        )
    except mysql.connector.Error:
        current_app.logger.exception("Customer dashboard database error")
        abort(500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/vehicles", methods=["POST"])
@customer_required
def add_customer_vehicle():
    plate = _normalise_plate(request.form.get("vehicle_number", ""))
    nickname = request.form.get("nickname", "").strip()[:50]
    if not re.fullmatch(r"[A-Z0-9]{6,15}", plate):
        flash("Enter a valid vehicle registration number.", "error")
        return redirect(url_for("customer.customer_dashboard"))

    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            """SELECT id, customer_id, is_active FROM customer_vehicles
               WHERE vehicle_number_normalized = %s LIMIT 1 FOR UPDATE""",
            (plate,),
        )
        existing = cursor.fetchone()
        if existing:
            if int(existing["customer_id"]) != int(session["customer_id"]):
                conn.rollback()
                flash("This vehicle is already linked to another customer account.", "error")
                return redirect(url_for("customer.customer_dashboard"))
            cursor.execute(
                """UPDATE customer_vehicles SET is_active = 1, nickname = %s
                   WHERE id = %s""",
                (nickname or None, existing["id"]),
            )
            flash(
                "Vehicle restored to your account. Its previous payment history has been retained.",
                "success",
            )
        else:
            cursor.execute(
                """INSERT INTO customer_vehicles
                   (customer_id, vehicle_number, vehicle_number_normalized, nickname, is_active)
                   VALUES (%s, %s, %s, %s, 1)""",
                (session["customer_id"], plate, plate, nickname or None),
            )
            flash("Vehicle added successfully.", "success")
        conn.commit()
    except mysql.connector.IntegrityError:
        if conn:
            conn.rollback()
        flash("This vehicle is already linked to a customer account.", "error")
    except mysql.connector.Error:
        if conn:
            conn.rollback()
        current_app.logger.exception("Add customer vehicle error")
        flash("Could not add this vehicle. Please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    return redirect(url_for("customer.customer_dashboard"))


@customer_bp.route("/vehicles/<int:vehicle_id>/remove", methods=["POST"])
@customer_required
def remove_customer_vehicle(vehicle_id):
    """Archive a vehicle; never delete its payment or receipt history."""
    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            """SELECT id, vehicle_number_normalized FROM customer_vehicles
               WHERE id = %s AND customer_id = %s AND is_active = 1
               FOR UPDATE""",
            (vehicle_id, session["customer_id"]),
        )
        vehicle = cursor.fetchone()
        if not vehicle:
            conn.rollback()
            flash("Vehicle was not found or is already removed.", "error")
            return redirect(url_for("customer.customer_dashboard"))

        cursor.execute(
            """SELECT id FROM parking_sessions
               WHERE REPLACE(REPLACE(UPPER(vehicle_number), ' ', ''), '-', '') = %s
                 AND status = 'PARKED' AND exit_time IS NULL LIMIT 1""",
            (vehicle["vehicle_number_normalized"],),
        )
        if cursor.fetchone():
            conn.rollback()
            flash(
                "This vehicle has an active parking session. Remove it after the vehicle exits.",
                "error",
            )
            return redirect(url_for("customer.customer_dashboard"))

        cursor.execute(
            """UPDATE customer_vehicles SET is_active = 0
               WHERE id = %s AND customer_id = %s""",
            (vehicle_id, session["customer_id"]),
        )
        conn.commit()
        flash(
            "Vehicle removed from your active list. Payment and receipt history has been retained.",
            "success",
        )
    except mysql.connector.Error:
        if conn:
            conn.rollback()
        current_app.logger.exception("Remove customer vehicle failed")
        flash("Could not remove this vehicle. Please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    return redirect(url_for("customer.customer_dashboard"))


@customer_bp.route("/api/vehicles/create-order", methods=["POST"])
@customer_required
def create_vehicle_registration_order():
    data = request.get_json(silent=True) or {}
    try:
        vehicle_id = int(data.get("vehicle_id", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid vehicle."}), 400

    conn = cursor = None
    try:
        client = _razorpay_client()
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            """SELECT id, vehicle_number FROM customer_vehicles
               WHERE id = %s AND customer_id = %s AND is_active = 1 FOR UPDATE""",
            (vehicle_id, session["customer_id"]),
        )
        vehicle = cursor.fetchone()
        if not vehicle:
            conn.rollback()
            return jsonify({"status": "error", "message": "Vehicle not found in your account."}), 404

        cursor.execute(
            """SELECT id FROM vehicle_registration_payments
               WHERE vehicle_id = %s AND customer_id = %s AND status = 'CAPTURED'
               LIMIT 1 FOR UPDATE""",
            (vehicle_id, session["customer_id"]),
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({"status": "paid", "message": "This vehicle's ₹50 registration payment is already complete."}), 409

        cursor.execute(
            """SELECT razorpay_order_id FROM vehicle_registration_payments
               WHERE vehicle_id = %s AND customer_id = %s AND status = 'CREATED'
                 AND razorpay_order_id IS NOT NULL
               ORDER BY id DESC LIMIT 1 FOR UPDATE""",
            (vehicle_id, session["customer_id"]),
        )
        pending = cursor.fetchone()
        if pending:
            conn.commit()
            return jsonify({
                "status": "success", "key_id": os.getenv("RAZORPAY_KEY_ID", ""),
                "order_id": pending["razorpay_order_id"], "amount": FIXED_FEE_PAISE,
                "currency": "INR", "name": "GUPIO Smart Parking",
                "description": "Vehicle registration fee - " + vehicle["vehicle_number"],
                "prefill": {},
            })

        order = client.order.create(data={
            "amount": FIXED_FEE_PAISE, "currency": "INR",
            "receipt": "gupio-vehicle-" + str(vehicle_id) + "-" + uuid.uuid4().hex[:12],
            "notes": {
                "customer_id": str(session["customer_id"]),
                "vehicle_id": str(vehicle_id),
                "vehicle_number": vehicle["vehicle_number"],
                "payment_type": "vehicle_registration",
            },
        })
        cursor.execute(
            """INSERT INTO vehicle_registration_payments
               (customer_id, vehicle_id, amount_paise, currency, razorpay_order_id, status)
               VALUES (%s, %s, %s, 'INR', %s, 'CREATED')""",
            (session["customer_id"], vehicle_id, FIXED_FEE_PAISE, order["id"]),
        )
        conn.commit()
        return jsonify({
            "status": "success", "key_id": os.getenv("RAZORPAY_KEY_ID", ""),
            "order_id": order["id"], "amount": FIXED_FEE_PAISE, "currency": "INR",
            "name": "GUPIO Smart Parking",
            "description": "Vehicle registration fee - " + vehicle["vehicle_number"],
            "prefill": {},
        })
    except Exception:
        if conn:
            conn.rollback()
        current_app.logger.exception("Vehicle registration Razorpay order creation failed")
        return jsonify({"status": "error", "message": "Unable to start vehicle payment. Please try again."}), 502
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/api/vehicles/verify-payment", methods=["POST"])
@customer_required
def verify_vehicle_registration_payment():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get("razorpay_order_id", ""))
    payment_id = str(data.get("razorpay_payment_id", ""))
    signature = str(data.get("razorpay_signature", ""))
    if not order_id or not payment_id or not signature:
        return jsonify({"status": "error", "message": "Missing payment verification details."}), 400

    conn = cursor = None
    try:
        client = _razorpay_client()
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        gateway_payment = client.payment.fetch(payment_id)
        if (
            gateway_payment.get("order_id") != order_id
            or int(gateway_payment.get("amount", 0)) != FIXED_FEE_PAISE
            or gateway_payment.get("currency") != "INR"
            or gateway_payment.get("status") != "captured"
        ):
            return jsonify({
                "status": "pending",
                "message": "Payment is not captured yet. Please wait for confirmation.",
            }), 202

        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            """SELECT * FROM vehicle_registration_payments
               WHERE razorpay_order_id = %s AND customer_id = %s FOR UPDATE""",
            (order_id, session["customer_id"]),
        )
        payment_row = cursor.fetchone()
        if not payment_row or int(payment_row["amount_paise"]) != FIXED_FEE_PAISE:
            conn.rollback()
            return jsonify({"status": "error", "message": "Vehicle payment order not found."}), 404

        cursor.execute(
            """UPDATE vehicle_registration_payments
               SET razorpay_payment_id = %s, status = 'CAPTURED',
                   captured_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s AND status <> 'CAPTURED'""",
            (payment_id, payment_row["id"]),
        )
        cursor.execute(
            "SELECT id FROM vehicle_registration_receipts WHERE payment_id = %s LIMIT 1",
            (payment_row["id"],),
        )
        if not cursor.fetchone():
            receipt_no = (
                "GUPIO-VEH-" + datetime.utcnow().strftime("%Y%m%d") + "-"
                + uuid.uuid4().hex[:8].upper()
            )
            cursor.execute(
                """INSERT INTO vehicle_registration_receipts
                   (payment_id, receipt_number, issued_at)
                   VALUES (%s, %s, CURRENT_TIMESTAMP)""",
                (payment_row["id"], receipt_no),
            )
        conn.commit()
        return jsonify({
            "status": "success",
            "message": "Vehicle registration payment verified successfully.",
        }), 200
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"status": "error", "message": "Payment signature verification failed."}), 400
    except Exception:
        if conn:
            conn.rollback()
        current_app.logger.exception("Vehicle registration payment verification failed")
        return jsonify({
            "status": "error",
            "message": "We could not verify this payment yet. Check payment history before retrying.",
        }), 502
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/api/create-qr", methods=["POST"])
@customer_required
def create_payment_qr():
    data = request.get_json(silent=True) or {}
    try:
        parking_session_id = int(data.get("parking_session_id", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid parking session."}), 400

    conn = cursor = None
    try:
        client = _razorpay_client()
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        parking = _customer_session(cursor, session["customer_id"], parking_session_id, lock=True)
        if not parking or parking["status"] != "PARKED" or parking["exit_time"] is not None:
            conn.rollback()
            return jsonify({"status": "error", "message": "This active parking session is not available for payment."}), 404

        cursor.execute(
            """SELECT p.id AS payment_id, p.status AS payment_status,
                      q.razorpay_qr_code_id, q.image_url, q.status AS qr_status
               FROM payments p JOIN payment_qr_codes q ON q.payment_id = p.id
               WHERE p.customer_id = %s AND p.parking_session_id = %s
                 AND p.status <> 'CAPTURED'
               ORDER BY p.id DESC LIMIT 1 FOR UPDATE""",
            (session["customer_id"], parking_session_id),
        )
        existing = cursor.fetchone()
        if existing and existing["qr_status"] == "ACTIVE":
            conn.commit()
            return jsonify({
                "status": "success", "payment_id": existing["payment_id"],
                "qr_code_id": existing["razorpay_qr_code_id"],
                "image_url": existing["image_url"], "amount": FIXED_FEE_PAISE,
                "amount_rupees": FIXED_FEE_RUPEES,
            })

        cursor.execute(
            """SELECT id FROM payments
               WHERE parking_session_id = %s AND customer_id = %s
                 AND status = 'CAPTURED' LIMIT 1""",
            (parking_session_id, session["customer_id"]),
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({"status": "paid", "message": "This parking session has already been paid."}), 409

        qr = client.qrcode.create({
            "type": "upi_qr",
            "name": "GUPIO Parking Session " + str(parking_session_id),
            "usage": "single_use",
            "fixed_amount": True,
            "payment_amount": FIXED_FEE_PAISE,
            "description": "GUPIO parking fee for session " + str(parking_session_id),
            "close_by": int((datetime.utcnow() + timedelta(hours=24)).timestamp()),
            "notes": {
                "parking_session_id": str(parking_session_id),
                "customer_id": str(session["customer_id"]),
            },
        })
        cursor.execute(
            """INSERT INTO payments
               (customer_id, parking_session_id, amount_paise, currency, razorpay_order_id, status)
               VALUES (%s, %s, %s, 'INR', NULL, 'CREATED')""",
            (session["customer_id"], parking_session_id, FIXED_FEE_PAISE),
        )
        payment_id = cursor.lastrowid
        cursor.execute(
            """INSERT INTO payment_qr_codes
               (payment_id, razorpay_qr_code_id, image_url, status, created_at)
               VALUES (%s, %s, %s, 'ACTIVE', CURRENT_TIMESTAMP)""",
            (payment_id, qr["id"], qr["image_url"]),
        )
        conn.commit()
        return jsonify({
            "status": "success", "payment_id": payment_id,
            "qr_code_id": qr["id"], "image_url": qr["image_url"],
            "amount": FIXED_FEE_PAISE, "amount_rupees": FIXED_FEE_RUPEES,
        })
    except Exception:
        if conn:
            conn.rollback()
        current_app.logger.exception("Razorpay QR creation failed")
        return jsonify({
            "status": "error",
            "message": "Unable to generate a Razorpay QR code. Confirm that UPI QR Code API access is enabled for your Razorpay account, then try again.",
        }), 502
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/api/qr-status/<int:payment_id>", methods=["GET"])
@customer_required
def payment_qr_status(payment_id):
    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT p.id, p.status, p.razorpay_payment_id, p.parking_session_id,
                      q.razorpay_qr_code_id, q.status AS qr_status
               FROM payments p JOIN payment_qr_codes q ON q.payment_id = p.id
               WHERE p.id = %s AND p.customer_id = %s LIMIT 1""",
            (payment_id, session["customer_id"]),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Payment not found."}), 404
        result = {"status": row["status"], "qr_status": row["qr_status"]}
        if row["status"] == "CAPTURED":
            cursor.execute("SELECT id FROM receipts WHERE payment_id = %s LIMIT 1", (payment_id,))
            if cursor.fetchone():
                result["receipt_url"] = url_for("customer.payment_receipt", payment_id=payment_id)
        return jsonify(result)
    except mysql.connector.Error:
        current_app.logger.exception("QR payment status lookup failed")
        return jsonify({"status": "error", "message": "Unable to check payment status."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/api/create-order", methods=["POST"])
@customer_required
def create_payment_order():
    data = request.get_json(silent=True) or {}
    try:
        parking_session_id = int(data.get("parking_session_id", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid parking session."}), 400

    conn = cursor = None
    try:
        client = _razorpay_client()
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        parking = _customer_session(cursor, session["customer_id"], parking_session_id, lock=True)
        if not parking or parking["status"] != "PARKED" or parking["exit_time"] is not None:
            conn.rollback()
            return jsonify({"status": "error", "message": "This active parking session is not available for checkout."}), 404
        cursor.execute(
            """SELECT id FROM payments WHERE parking_session_id = %s
               AND customer_id = %s AND status = 'CAPTURED' LIMIT 1""",
            (parking_session_id, session["customer_id"]),
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({"status": "error", "message": "This parking session has already been paid."}), 409

        order = client.order.create(data={
            "amount": FIXED_FEE_PAISE,
            "currency": "INR",
            "receipt": "gupio-" + str(parking_session_id) + "-" + uuid.uuid4().hex[:12],
            "notes": {
                "parking_session_id": str(parking_session_id),
                "customer_id": str(session["customer_id"]),
            },
        })
        cursor.execute(
            """INSERT INTO payments
               (customer_id, parking_session_id, amount_paise, currency, razorpay_order_id, status)
               VALUES (%s, %s, %s, 'INR', %s, 'CREATED')""",
            (session["customer_id"], parking_session_id, FIXED_FEE_PAISE, order["id"]),
        )
        conn.commit()
        return jsonify({
            "status": "success", "key_id": os.getenv("RAZORPAY_KEY_ID"),
            "order_id": order["id"], "amount": FIXED_FEE_PAISE,
            "currency": "INR", "name": "GUPIO Smart Parking",
            "description": "Fixed parking fee", "prefill": {},
        })
    except Exception:
        if conn:
            conn.rollback()
        current_app.logger.exception("Razorpay order creation failed")
        return jsonify({"status": "error", "message": "Unable to start payment. Please try again."}), 502
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/api/verify-payment", methods=["POST"])
@customer_required
def verify_payment():
    data = request.get_json(silent=True) or {}
    order_id = str(data.get("razorpay_order_id", ""))
    payment_id = str(data.get("razorpay_payment_id", ""))
    signature = str(data.get("razorpay_signature", ""))
    if not order_id or not payment_id or not signature:
        return jsonify({"status": "error", "message": "Missing payment verification details."}), 400

    conn = cursor = None
    try:
        client = _razorpay_client()
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        gateway_payment = client.payment.fetch(payment_id)
        if (
            gateway_payment.get("order_id") != order_id
            or int(gateway_payment.get("amount", 0)) != FIXED_FEE_PAISE
            or gateway_payment.get("currency") != "INR"
            or gateway_payment.get("status") != "captured"
        ):
            return jsonify({
                "status": "pending",
                "message": "Payment has not yet been captured. Please wait for confirmation.",
            }), 202

        conn = _db()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        cursor.execute(
            "SELECT * FROM payments WHERE razorpay_order_id = %s AND customer_id = %s FOR UPDATE",
            (order_id, session["customer_id"]),
        )
        payment_row = cursor.fetchone()
        if not payment_row or int(payment_row["amount_paise"]) != FIXED_FEE_PAISE:
            conn.rollback()
            return jsonify({"status": "error", "message": "Payment order not found."}), 404
        _mark_payment_captured(cursor, payment_row, payment_id)
        conn.commit()
        return jsonify({
            "status": "success", "message": "Payment verified successfully.",
            "receipt_url": url_for("customer.payment_receipt", payment_id=payment_row["id"]),
        }), 200
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"status": "error", "message": "Payment signature verification failed."}), 400
    except Exception:
        if conn:
            conn.rollback()
        current_app.logger.exception("Razorpay payment verification failed")
        return jsonify({
            "status": "error",
            "message": "We could not verify this payment yet. If money was deducted, check payment history before retrying.",
        }), 502
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/history")
@customer_required
def payment_history():
    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        rows = _get_customer_payment_history(cursor, session["customer_id"], 200)
        return render_template("customer_history.html", payments=rows)
    except mysql.connector.Error:
        current_app.logger.exception("Payment history error")
        abort(500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@customer_bp.route("/receipt/<int:payment_id>")
@customer_required
def payment_receipt(payment_id):
    conn = cursor = None
    try:
        conn = _db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT p.id, p.parking_session_id, p.amount_paise, p.currency, p.status,
                      p.razorpay_payment_id, p.captured_at, ps.vehicle_number,
                      ps.entry_time, ps.exit_time, r.receipt_number, r.issued_at
               FROM payments p
               JOIN parking_sessions ps ON ps.id = p.parking_session_id
               JOIN receipts r ON r.payment_id = p.id
               WHERE p.id = %s AND p.customer_id = %s AND p.status = 'CAPTURED'
               LIMIT 1""",
            (payment_id, session["customer_id"]),
        )
        receipt = cursor.fetchone()
        if not receipt:
            abort(404)
        return render_template("customer_receipt.html", receipt=receipt)
    except mysql.connector.Error:
        current_app.logger.exception("Receipt lookup error")
        abort(500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def register_customer_portal(app, db_connection):
    app.config["GUPIO_DB_CONNECTOR"] = db_connection
    app.register_blueprint(customer_bp)

    @app.route("/api/razorpay/webhook", methods=["POST"])
    def razorpay_webhook():
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
        signature = request.headers.get("X-Razorpay-Signature", "")
        event_id = request.headers.get("X-Razorpay-Event-Id", "")
        raw_body = request.get_data()

        if not webhook_secret or not signature:
            return jsonify({"status": "error"}), 400

        expected = hmac.new(
            webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return jsonify({"status": "error"}), 400

        import json
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            event_type = payload.get("event", "unknown")
            payload_data = payload.get("payload", {})
            payment_entity = payload_data.get("payment", {}).get("entity", {})
            qr_entity = payload_data.get("qr_code", {}).get("entity", {})
            order_id = payment_entity.get("order_id")
            payment_id = payment_entity.get("id")
            qr_code_id = qr_entity.get("id")
            if not event_id:
                event_id = hashlib.sha256(raw_body).hexdigest()
        except Exception:
            return jsonify({"status": "error"}), 400

        conn = cursor = None
        try:
            conn = db_connection()
            cursor = conn.cursor(dictionary=True)
            conn.start_transaction()
            cursor.execute(
                """INSERT IGNORE INTO payment_webhooks
                   (event_id, event_type, payload_sha256)
                   VALUES (%s, %s, %s)""",
                (event_id, event_type, hashlib.sha256(raw_body).hexdigest()),
            )
            if cursor.rowcount == 0:
                conn.commit()
                return jsonify({"status": "duplicate"}), 200

            if order_id and payment_id and event_type in ("payment.captured", "payment.failed"):
                cursor.execute(
                    "SELECT * FROM payments WHERE razorpay_order_id = %s FOR UPDATE",
                    (order_id,),
                )
                payment_row = cursor.fetchone()
                if payment_row:
                    if (
                        event_type == "payment.captured"
                        and int(payment_entity.get("amount", 0)) == payment_row["amount_paise"] == FIXED_FEE_PAISE
                        and payment_entity.get("currency") == "INR"
                    ):
                        _mark_payment_captured(cursor, payment_row, payment_id)
                    elif event_type == "payment.failed" and payment_row["status"] != "CAPTURED":
                        cursor.execute(
                            """UPDATE payments SET status = 'FAILED',
                               razorpay_payment_id = %s, updated_at = CURRENT_TIMESTAMP
                               WHERE id = %s""",
                            (payment_id, payment_row["id"]),
                        )
                else:
                    cursor.execute(
                        """SELECT * FROM vehicle_registration_payments
                           WHERE razorpay_order_id = %s FOR UPDATE""",
                        (order_id,),
                    )
                    vehicle_payment = cursor.fetchone()
                    if vehicle_payment:
                        if (
                            event_type == "payment.captured"
                            and int(payment_entity.get("amount", 0)) == vehicle_payment["amount_paise"] == FIXED_FEE_PAISE
                            and payment_entity.get("currency") == "INR"
                        ):
                            cursor.execute(
                                """UPDATE vehicle_registration_payments
                                   SET razorpay_payment_id = %s, status = 'CAPTURED',
                                       captured_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                                   WHERE id = %s AND status <> 'CAPTURED'""",
                                (payment_id, vehicle_payment["id"]),
                            )
                            cursor.execute(
                                "SELECT id FROM vehicle_registration_receipts WHERE payment_id = %s LIMIT 1",
                                (vehicle_payment["id"],),
                            )
                            if not cursor.fetchone():
                                receipt_no = (
                                    "GUPIO-VEH-" + datetime.utcnow().strftime("%Y%m%d")
                                    + "-" + uuid.uuid4().hex[:8].upper()
                                )
                                cursor.execute(
                                    """INSERT INTO vehicle_registration_receipts
                                       (payment_id, receipt_number, issued_at)
                                       VALUES (%s, %s, CURRENT_TIMESTAMP)""",
                                    (vehicle_payment["id"], receipt_no),
                                )
                        elif event_type == "payment.failed" and vehicle_payment["status"] != "CAPTURED":
                            cursor.execute(
                                """UPDATE vehicle_registration_payments
                                   SET status = 'FAILED', razorpay_payment_id = %s,
                                       updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                                (payment_id, vehicle_payment["id"]),
                            )

            if event_type == "qr_code.credited" and qr_code_id and payment_id:
                cursor.execute(
                    """SELECT p.* FROM payments p
                       JOIN payment_qr_codes q ON q.payment_id = p.id
                       WHERE q.razorpay_qr_code_id = %s FOR UPDATE""",
                    (qr_code_id,),
                )
                payment_row = cursor.fetchone()
                if payment_row:
                    amount_ok = (
                        int(payment_entity.get("amount", 0))
                        == payment_row["amount_paise"] == FIXED_FEE_PAISE
                    )
                    currency_ok = payment_entity.get("currency") == "INR"
                    captured_ok = (
                        payment_entity.get("status") == "captured"
                        or payment_entity.get("captured") is True
                    )
                    if amount_ok and currency_ok and captured_ok:
                        _mark_payment_captured(cursor, payment_row, payment_id)
                        cursor.execute(
                            """UPDATE payment_qr_codes SET status = 'PAID',
                               updated_at = CURRENT_TIMESTAMP WHERE payment_id = %s""",
                            (payment_row["id"],),
                        )

            conn.commit()
            return jsonify({"status": "ok"}), 200
        except Exception:
            if conn:
                conn.rollback()
            current_app.logger.exception("Razorpay webhook processing error")
            return jsonify({"status": "error"}), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
