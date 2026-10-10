from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
from io import BytesIO, StringIO
import csv
import hashlib
import secrets
import qrcode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import or_
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import (Blueprint, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for, send_file)
from . import db
from .models import (User, ParkingSlot, Reservation, ParkingSession, Payment,
                     SystemLog, Notification, HardwareStatus, utcnow)
from .services import (admit_reservation, analytics, cancel_reservation, close_session,
                       create_reservation, first_available_slot, make_payment, notify,
                       slot_payload, start_session, sync_sensor_state, walk_in,
                       reschedule_reservation, cancel_admission, calculate_fee, log, email_user)
from .receipts import receipt_pdf
from .email_service import send_email
from .planner import reservation_plan, allocation_experiment

bp = Blueprint('main', __name__)


def current_user():
    user_id = session.get('user_id')
    return db.session.get(User, user_id) if user_id else None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for('main.login', next=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.role != 'admin':
            flash('Administrator access required.', 'danger')
            return redirect(url_for('main.dashboard')) if user else redirect(url_for('main.login'))
        return view(*args, **kwargs)
    return wrapper


def owns(record):
    user = current_user()
    return user and (user.role == 'admin' or getattr(record, 'user_id', None) == user.id)


def parse_datetime_fields(values=None):
    try:
        values = request.form if values is None else values
        day = date.fromisoformat(values['date'])
        local_zone = configured_zone()
        start = datetime.combine(day, time.fromisoformat(values['start']), tzinfo=local_zone)
        end = datetime.combine(day, time.fromisoformat(values['end']), tzinfo=local_zone)
        return (start.astimezone(timezone.utc).replace(tzinfo=None),
                end.astimezone(timezone.utc).replace(tzinfo=None))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Enter a valid date and arrival/departure time.') from exc


def configured_zone():
    try:
        return ZoneInfo(current_app.config.get('TIMEZONE', 'UTC'))
    except ZoneInfoNotFoundError as exc:
        raise ValueError('ParkSmart has an invalid TIMEZONE configuration.') from exc


def local_display(value, fmt='%d %b %Y %H:%M'):
    if not value:
        return ''
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    return value.replace(tzinfo=timezone.utc).astimezone(configured_zone()).strftime(fmt)


@bp.context_processor
def inject_context():
    user = current_user()
    unread = Notification.query.filter_by(user_id=user.id, read_status=False).count() if user else 0
    return {'current_user': user, 'unread_notifications': unread,
            'currency': current_app.config['CURRENCY'],
            'timezone_name': current_app.config.get('TIMEZONE', 'UTC')}


@bp.app_template_filter('localtime')
def localtime_filter(value, fmt='%d %b %Y %H:%M'):
    return local_display(value, fmt)


@bp.route('/')
def home():
    return render_template('home.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email, active=True).first()
        if user and user.check_password(request.form.get('password', '')):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            next_url = request.form.get('next') or request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('main.admin' if user.role == 'admin' else 'main.dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', next=request.args.get('next', ''))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = ' '.join(request.form.get('name', '').strip().split())
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        vehicle = request.form.get('vehicle_number', '').strip().upper()
        if not name or len(name) > 100 or len(password) < 8:
            flash('Enter a name and a password with at least 8 characters.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'warning')
        else:
            try:
                vehicle = vehicle or 'NOT PROVIDED'
                user = User(name=name, email=email, vehicle_number=vehicle)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash('Account created. Please log in.', 'success')
                return redirect(url_for('main.login'))
            except Exception:
                db.session.rollback()
                flash('Could not create that account.', 'danger')
    return render_template('register.html')


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.home'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()
    if request.method == 'POST':
        name = ' '.join(request.form.get('name', '').strip().split())
        vehicle = ' '.join(request.form.get('vehicle_number', '').strip().upper().split())
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        if not name or len(name) > 100 or not vehicle or len(vehicle) > 30:
            flash('Enter a valid name and vehicle number.', 'danger')
        elif new_password and (len(new_password) < 8 or not user.check_password(current_password)):
            flash('To change your password, enter your current password and a new password with at least 8 characters.', 'danger')
        else:
            user.name, user.vehicle_number = name, vehicle
            if new_password:
                user.set_password(new_password)
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('main.profile'))
    return render_template('profile.html')


def reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='parksmart-password-reset')


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email', '').strip().lower(), active=True).first()
        if user:
            token = reset_serializer().dumps({'id': user.id, 'version': hashlib.sha256(user.password_hash.encode()).hexdigest()})
            link = current_app.config['PUBLIC_BASE_URL'] + url_for('main.reset_password', token=token)
            email_user(user, 'Reset your ParkSmart password', f'Use this link within 30 minutes to reset your password:\n{link}')
        flash('If that email belongs to an active account, a reset link has been requested. Check your inbox.', 'info')
        return redirect(url_for('main.login'))
    return render_template('password_reset.html', reset=False)


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        data = reset_serializer().loads(token, max_age=1800)
        user = db.session.get(User, data['id'])
        if not user or not user.active or data['version'] != hashlib.sha256(user.password_hash.encode()).hexdigest():
            raise BadSignature('Link no longer valid')
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        flash('This reset link is invalid or expired. Request a new one.', 'warning')
        return redirect(url_for('main.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        if len(password) < 8 or password != request.form.get('confirm_password'):
            flash('Use at least 8 characters and make sure both passwords match.', 'danger')
        else:
            user.set_password(password)
            log('PASSWORD_RESET', f'Password reset for user {user.id}')
            db.session.commit()
            session.clear()
            flash('Password updated. Sign in with your new password.', 'success')
            return redirect(url_for('main.login'))
    return render_template('password_reset.html', reset=True)


@bp.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
    reservations = Reservation.query.filter_by(user_id=user.id).order_by(Reservation.created_at.desc()).limit(8).all()
    sessions = ParkingSession.query.filter_by(user_id=user.id).order_by(ParkingSession.entry_time.desc()).limit(8).all()
    notifications = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(5).all()
    active = ParkingSession.query.filter_by(user_id=user.id).filter(ParkingSession.status.in_(['awaiting_entry', 'active'])).first()
    slot_views = {s.id: slot_payload(s) for s in slots}
    return render_template('dashboard.html', slots=slots, reservations=reservations, sessions=sessions,
                           notifications=notifications, active_session=active, slot_views=slot_views,
                           available=sum(s['status'] == 'available' for s in slot_views.values()),
                           occupied=sum(s.enabled and s.sensor_occupied for s in slots))


@bp.route('/reserve', methods=['GET', 'POST'])
@login_required
def reserve():
    slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
    availability = {slot.id: {'status': slot_payload(slot)['status'], 'health': slot.sensor_health} for slot in slots}
    if request.method == 'POST':
        try:
            start, end = parse_datetime_fields()
            booking = create_reservation(current_user(), int(request.form['slot_id']), request.form.get('vehicle_number'), start, end)
            return redirect(url_for('main.reservation_success', rid=booking.id))
        except (ValueError, TypeError) as exc:
            flash(str(exc), 'danger')
    local_today = datetime.now(timezone.utc).astimezone(configured_zone()).date().isoformat()
    return render_template('reserve.html', slots=slots, availability=availability,
                           default_vehicle=current_user().vehicle_number, now_date=local_today)


@bp.route('/reservation/<int:rid>')
@login_required
def reservation_success(rid):
    booking = db.session.get(Reservation, rid)
    if not booking or not owns(booking):
        abort(404)
    return render_template('reservation_success.html', r=booking)


@bp.route('/api/reservation-plan')
@login_required
def api_reservation_plan():
    try:
        plan = reservation_plan(*parse_datetime_fields(request.args), vehicle=request.args.get('vehicle_number'))
        for option in plan['alternatives']:
            option['date'] = local_display(option['start'], '%Y-%m-%d')
            option['start'] = local_display(option['start'], '%H:%M')
            option['end'] = local_display(option['end'], '%H:%M')
        return jsonify(plan)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@bp.route('/admin/allocation-lab')
@admin_required
def allocation_lab():
    try:
        experiment = allocation_experiment(
            request.args.get('scenario', 'fragmentation'), int(request.args.get('seed', '42')),
            int(request.args.get('slots', '4')), int(request.args.get('requests', '80')))
    except (ValueError, TypeError) as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('main.allocation_lab'))
    if request.args.get('format') == 'csv':
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Scenario', 'Seed', 'Slots', 'Requests', 'Horizon (min)', 'Policy',
                         'Request', 'Start (min)', 'End (min)', 'Assigned slot', 'Containing gap (min)'])
        for strategy, result in experiment['results'].items():
            for row in result['trace']:
                writer.writerow([experiment['scenario'], experiment['seed'], experiment['slot_count'],
                                 experiment['request_count'], experiment['horizon_minutes'], strategy,
                                 row['request'], row['start'], row['end'], row['slot'] or 'REJECTED',
                                 row['gap_minutes'] if row['gap_minutes'] is not None else ''])
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = 'attachment; filename=allocation_experiment.csv'
        return response
    return render_template('allocation_lab.html', experiment=experiment)


@bp.route('/reservation/<int:rid>/cancel', methods=['POST'])
@login_required
def reservation_cancel(rid):
    booking = db.session.get(Reservation, rid)
    if not booking or not owns(booking):
        abort(404)
    try:
        cancel_reservation(booking)
        flash('Reservation cancelled.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(request.referrer or url_for('main.dashboard'))


@bp.route('/reservation/<int:rid>/edit', methods=['GET', 'POST'])
@login_required
def reservation_edit(rid):
    booking = db.session.get(Reservation, rid)
    if not booking or not owns(booking):
        abort(404)
    if request.method == 'POST':
        try:
            reschedule_reservation(booking, *parse_datetime_fields())
            flash('Reservation rescheduled. Your QR token stays the same.', 'success')
            return redirect(url_for('main.reservation_success', rid=rid))
        except ValueError as exc:
            flash(str(exc), 'danger')
    local_today = datetime.now(timezone.utc).astimezone(configured_zone()).date().isoformat()
    return render_template('reservation_edit.html', booking=booking, now_date=local_today)


@bp.route('/reservation/<int:rid>/qr.png')
@login_required
def reservation_qr(rid):
    booking = db.session.get(Reservation, rid)
    if not booking or not owns(booking):
        abort(404)
    image = qrcode.make(f'PARKSMART:{booking.qr_token}')
    buf = BytesIO()
    image.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@bp.route('/entry', methods=['GET', 'POST'])
@login_required
def entry():
    if request.method == 'POST':
        try:
            if request.form.get('qr_token'):
                parking = admit_reservation(request.form['qr_token'], current_user())
            else:
                parking = walk_in(request.form.get('vehicle_number') or current_user().vehicle_number, current_user().id)
            flash(f'Gate opened. {parking.slot.slot_number} is assigned; enter until the IR sensor confirms occupancy.', 'success')
            return redirect(url_for('main.dashboard'))
        except ValueError as exc:
            flash(str(exc), 'danger')
    return render_template('entry.html')


@bp.route('/notifications')
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=current_user().id).order_by(Notification.created_at.desc()).all()
    for item in items:
        item.read_status = True
    db.session.commit()
    return render_template('notifications.html', notifications=items)


@bp.route('/history')
@login_required
def history():
    query = ParkingSession.query.filter_by(user_id=current_user().id)
    search = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    if search:
        query = query.filter(ParkingSession.vehicle_number.ilike(f'%{search}%'))
    if status in {'active', 'awaiting_entry', 'completed', 'cancelled'}:
        query = query.filter_by(status=status)
    sessions = query.order_by(ParkingSession.entry_time.desc()).all()
    return render_template('history.html', sessions=sessions, search=search, selected_status=status)


@bp.route('/session/<int:sid>/cancel', methods=['POST'])
@login_required
def admission_cancel(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    try:
        cancel_admission(parking)
        flash('Entry cancelled and space released.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('main.admin' if current_user().role == 'admin' else 'main.dashboard'))


@bp.route('/api/fee-estimate')
def fee_estimate():
    try:
        minutes = int(request.args.get('minutes', '60'))
        if not 1 <= minutes <= 10080:
            raise ValueError()
    except ValueError:
        return jsonify({'error': 'Enter a duration between 1 and 10080 minutes.'}), 400
    amount = calculate_fee(minutes, current_app.config['PARKING_RATE_FIRST_HOUR'], current_app.config['PARKING_RATE_ADDITIONAL_HOUR'])
    return jsonify({'minutes': minutes, 'amount': amount, 'currency': current_app.config['CURRENCY']})


@bp.route('/session/<int:sid>/close', methods=['POST'])
@login_required
def close(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    try:
        close_session(parking)
        flash('Exit recorded. Please pay the generated bill.', 'success')
        return redirect(url_for('main.bill', sid=sid))
    except ValueError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('main.dashboard'))


@bp.route('/bill/<int:sid>')
@login_required
def bill(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    return render_template('bill.html', s=parking, payment=Payment.query.filter_by(session_id=sid).first())


@bp.route('/pay/<int:sid>', methods=['POST'])
@login_required
def pay(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    try:
        make_payment(parking)
        flash('Simulated payment successful. Receipt generated.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('main.bill', sid=sid))


@bp.route('/bill/<int:sid>/pdf')
@login_required
def bill_pdf(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    return send_file(BytesIO(receipt_pdf(parking)), as_attachment=True,
                     download_name=f'parksmart_receipt_{sid}.pdf', mimetype='application/pdf')


@bp.route('/bill/<int:sid>/email', methods=['POST'])
@login_required
def bill_email(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking or not owns(parking):
        abort(404)
    ok, message = send_email(current_user().email, 'ParkSmart parking receipt',
                             f'Your ParkSmart receipt for {parking.vehicle_number} is attached.',
                             receipt_pdf(parking), f'parksmart_receipt_{sid}.pdf')
    flash(message, 'success' if ok else 'warning')
    return redirect(url_for('main.bill', sid=sid))


@bp.route('/api/slots')
def api_slots():
    return jsonify({'slots': [slot_payload(s) for s in ParkingSlot.query.order_by(ParkingSlot.id).all()],
                    'server_time': utcnow().isoformat() + 'Z'})


@bp.route('/api/hardware')
@admin_required
def api_hardware():
    status = db.session.get(HardwareStatus, 1)
    stale = not status or not status.last_seen or (utcnow() - status.last_seen).total_seconds() > current_app.config['HARDWARE_STALE_SECONDS']
    return jsonify({'connected': bool(status and status.connected and not stale),
                    'gate': status.gate_state if status else 'unknown',
                    'gate_health': status.gate_health if status else 'unknown',
                    'last_seen': status.last_seen.isoformat() if status and status.last_seen else None,
                    'error': status.last_error if status else 'Not initialized',
                    'mode': 'simulator' if current_app.config['SIMULATOR_MODE'] else 'esp32'})


@bp.route('/api/simulator/sensors', methods=['POST'])
@admin_required
def simulator_sensors():
    try:
        current_app.extensions['hardware'].update_simulator((request.get_json(silent=True) or {}).get('occupied'))
        return jsonify({'ok': True, 'slots': [slot_payload(s) for s in ParkingSlot.query.order_by(ParkingSlot.id).all()]})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@bp.route('/api/analytics')
@admin_required
def api_analytics():
    return jsonify(analytics())


@bp.route('/admin/export/<kind>')
@admin_required
def admin_export(kind):
    exports = {
        'sessions': (
            'parking_sessions.csv',
            ['ID', 'Vehicle', 'Slot', 'Status', 'Entry', 'Exit', 'Duration (min)', 'Fee', 'Payment'],
            lambda: [[s.id, s.vehicle_number, s.slot.slot_number, s.status, s.entry_time, s.exit_time or '',
              s.duration_minutes or '', f'{s.fee or 0:.2f}', s.payment_status]
             for s in ParkingSession.query.order_by(ParkingSession.entry_time.desc()).all()],
        ),
        'reservations': (
            'reservations.csv',
            ['Reference', 'Driver', 'Vehicle', 'Slot', 'Start', 'End', 'Status'],
            lambda: [[r.reference, r.user.email, r.vehicle_number, r.slot.slot_number,
              r.starts_at, r.ends_at, r.status]
             for r in Reservation.query.order_by(Reservation.created_at.desc()).all()],
        ),
        'logs': (
            'system_logs.csv',
            ['Timestamp', 'Severity', 'Event', 'Description'],
            lambda: [[log.timestamp, log.severity, log.event, log.description]
             for log in SystemLog.query.order_by(SystemLog.timestamp.desc()).all()],
        ),
    }
    if kind not in exports:
        abort(404)
    filename, headers, rows = exports[kind]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    # Keep user-entered strings as text when opened in spreadsheet software.
    writer.writerows(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value
                     for value in row] for row in rows())
    response = make_response('\ufeff' + output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@bp.route('/admin')
@admin_required
def admin():
    slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
    sessions = ParkingSession.query.order_by(ParkingSession.entry_time.desc()).limit(30).all()
    reservations = Reservation.query.order_by(Reservation.created_at.desc()).limit(30).all()
    users = User.query.order_by(User.created_at.desc()).limit(30).all()
    severity = request.args.get('severity', '').upper()
    search = request.args.get('q', '').strip()
    logs_query = SystemLog.query
    if severity in {'INFO', 'WARNING', 'ERROR'}:
        logs_query = logs_query.filter_by(severity=severity)
    if search:
        pattern = f'%{search}%'
        logs_query = logs_query.filter(or_(SystemLog.event.ilike(pattern), SystemLog.description.ilike(pattern)))
    logs = logs_query.order_by(SystemLog.timestamp.desc()).limit(80).all()
    health = db.session.get(HardwareStatus, 1)
    slot_views = {s.id: slot_payload(s, include_vehicle=True) for s in slots}
    return render_template('admin.html', slots=slots, sessions=sessions, reservations=reservations,
                           users=users, logs=logs, health=health, metrics=analytics(),
                           log_severity=severity, log_search=search, slot_views=slot_views)


@bp.route('/admin/walk-in', methods=['POST'])
@admin_required
def admin_start():
    try:
        parking = walk_in(request.form.get('vehicle'), None)
        flash(f'{parking.vehicle_number} assigned to {parking.slot.slot_number}. Gate opened.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('main.admin'))


@bp.route('/admin/admit', methods=['POST'])
@admin_required
def admin_admit():
    try:
        parking = admit_reservation(request.form.get('qr_token'), current_user())
        flash(f'Reservation admitted to {parking.slot.slot_number}. Gate opened.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('main.admin'))


@bp.route('/admin/session/<int:sid>/close', methods=['POST'])
@admin_required
def admin_close(sid):
    parking = db.session.get(ParkingSession, sid)
    if not parking:
        abort(404)
    try:
        close_session(parking)
        flash(f'Exit recorded for {parking.vehicle_number}.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('main.admin'))


@bp.route('/admin/slot/<int:slot_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_slot(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if not slot:
        abort(404)
    if active := ParkingSession.query.filter_by(slot_id=slot.id, exit_time=None).first():
        flash('An active session must end before disabling this slot.', 'warning')
    else:
        slot.enabled = not slot.enabled
        slot.status = ('occupied' if slot.sensor_occupied else 'available') if slot.enabled else 'disabled'
        db.session.commit()
        flash(f'{slot.slot_number} is now {"enabled" if slot.enabled else "disabled"}.', 'success')
    return redirect(url_for('main.admin'))


@bp.route('/admin/reservation/<int:rid>/cancel', methods=['POST'])
@admin_required
def admin_cancel_reservation(rid):
    booking = db.session.get(Reservation, rid)
    if not booking:
        abort(404)
    try:
        cancel_reservation(booking)
        flash('Reservation cancelled.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('main.admin'))


@bp.route('/admin/user/<int:user_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.id == current_user().id:
        abort(404)
    user.active = not user.active
    db.session.commit()
    flash(f'{user.email} is now {"active" if user.active else "disabled"}.', 'success')
    return redirect(url_for('main.admin'))


@bp.route('/admin/gate', methods=['POST'])
@admin_required
def admin_gate():
    try:
        current_app.extensions['hardware'].command_gate(request.form.get('action') == 'open')
        flash('Gate command sent.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('main.admin'))
