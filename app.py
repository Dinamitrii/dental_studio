import functools
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from image_optimization import image_attributes
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DEFAULT = {
    'name': 'Ясна', 'phone': '', 'email': '',
    'address': 'София · адресът предстои да бъде добавен',
    'hours': 'Понеделник – петък: 09:00–19:00',
    'intro': 'Време да се усмихнете спокойно.',
    'description': 'Грижа с внимание към Вас. От първия разговор до последния детайл в усмивката Ви.',
    'hero': '/static/clinic.jpg',
    'services': [
        {'name': 'Профилактика и преглед', 'text': 'Внимателен преглед, разговор и индивидуален план за Вашето орално здраве.', 'price': '30', 'icon': '01'},
        {'name': 'Почистване и полиране', 'text': 'Професионална грижа за чистотата на зъбите и здравето на венците.', 'price': '65', 'icon': '02'},
        {'name': 'Лечение на кариеси', 'text': 'Възстановяване с внимание към естествената форма и цвят на зъба.', 'price': '70', 'icon': '03'},
        {'name': 'Детска стоматология', 'text': 'Спокоен подход и време за запознаване за нашите най-малки посетители.', 'price': '30', 'icon': '04'},
        {'name': 'Естетична стоматология', 'text': 'Консултация за възможностите за естествена и хармонична усмивка.', 'price': '', 'icon': '05'},
        {'name': 'Възстановяване на зъби', 'text': 'Индивидуално обсъждане на корони, мостове и протетични решения.', 'price': '', 'icon': '06'}
    ],
    'team': [
        {'name': 'Вашият лекуващ стоматолог', 'role': 'Обща дентална медицина', 'bio': 'Тук ще представим лекаря, неговия опит, образование и подход към пациентите.', 'image': ''},
        {'name': 'Вашият дентален асистент', 'role': 'Грижа и организация', 'bio': 'Човекът, който Ви посреща и помага посещението Ви да протече спокойно.', 'image': ''}
    ]
}
STATUSES = {'new': 'Нова', 'confirmed': 'Потвърдена', 'done': 'Приключена', 'cancelled': 'Отказана'}


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(ROOT / 'instance'))
    app.config.update(MAX_CONTENT_LENGTH=5 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', DATABASE=str(ROOT / 'instance/dental.sqlite3'))
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(exist_ok=True)
    keyfile = Path(app.instance_path) / 'session.key'
    if not app.config.get('SECRET_KEY'):
        try:
            with keyfile.open('x') as f:
                os.chmod(keyfile, 0o600)
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = os.environ.get('DENTAL_SECRET_KEY') or keyfile.read_text()
    CSRFProtect(app)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=15)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    with app.app_context():
        db().executescript('''
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin (id INTEGER PRIMARY KEY, password TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
                day TEXT NOT NULL, period TEXT NOT NULL, patient TEXT NOT NULL,
                service TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS limits (bucket TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
        ''')
        db().execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps(DEFAULT, ensure_ascii=False),))
        db().commit()

    def settings():
        return json.loads(db().execute('SELECT data FROM settings WHERE id=1').fetchone()['data'])

    def limited(bucket, maximum, seconds):
        now = time.time()
        db().execute('INSERT INTO limits VALUES (?, ?, 1) ON CONFLICT(bucket) DO UPDATE SET '
                     'count=CASE WHEN started < ? THEN 1 ELSE count+1 END, '
                     'started=CASE WHEN started < ? THEN ? ELSE started END',
                     (bucket, now, now-seconds, now-seconds, now))
        count = db().execute('SELECT count FROM limits WHERE bucket=?', (bucket,)).fetchone()[0]
        db().commit()
        return count > maximum

    def admin_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    @app.context_processor
    def context():
        return dict(site=settings(), image_attributes=lambda source: image_attributes(app, source), statuses=STATUSES, today=datetime.now(ZoneInfo('Europe/Sofia')).date().isoformat())

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        if request.path.startswith('/admin') or request.path.startswith('/appointment'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def home():
        return render_template('home.html', title='Дентално студио Ясна')

    @app.get('/<page>')
    def page(page):
        titles = {'services': 'Грижа за всяка усмивка', 'team': 'Хората зад Вашата усмивка',
                  'prices': 'Ясни цени. Спокойни решения.', 'contact': 'Нека се запознаем', 'privacy': 'Поверителност'}
        if page not in titles:
            abort(404)
        return render_template('page.html', page=page, title=titles[page])

    @app.route('/appointment', methods=['GET', 'POST'])
    def appointment():
        errors = []
        if request.method == 'POST':
            data = {key: request.form.get(key, '').strip() for key in ('name', 'phone', 'day', 'period', 'patient', 'service')}
            if request.form.get('website') or limited('booking:' + (request.remote_addr or ''), 5, 3600):
                errors.append('Твърде много заявки. Моля, опитайте отново по-късно.')
            if not 2 <= len(data['name']) <= 100:
                errors.append('Въведете име между 2 и 100 символа.')
            if not re.fullmatch(r'\+?[\d ()-]{7,24}', data['phone']) or not 7 <= len(re.sub(r'\D', '', data['phone'])) <= 15:
                errors.append('Въведете валиден телефон за връзка.')
            try:
                delta = (datetime.strptime(data['day'], '%Y-%m-%d').date() - datetime.now(ZoneInfo('Europe/Sofia')).date()).days
                if not 0 <= delta <= 180:
                    raise ValueError()
            except ValueError:
                errors.append('Изберете дата в следващите 180 дни.')
            if data['period'] not in ('09:00–12:00', '12:00–15:00', '15:00–19:00') or data['patient'] not in ('Нов пациент', 'Настоящ пациент'):
                errors.append('Изберете удобен часови диапазон и тип пациент.')
            if data['service'] not in [s['name'] for s in settings()['services']]:
                errors.append('Изберете услуга от списъка.')
            if not request.form.get('consent'):
                errors.append('Потвърдете, че сте запознати с обработката на данните.')
            if not errors:
                db().execute('INSERT INTO bookings (name,phone,day,period,patient,service,created) VALUES (?,?,?,?,?,?,?)',
                             (*data.values(), datetime.now(ZoneInfo('Europe/Sofia')).isoformat()))
                db().commit()
                session['booked'] = True
                return redirect(url_for('thanks'))
        return render_template('booking.html', title='Заявете своя час', errors=errors)

    @app.get('/appointment/thanks')
    def thanks():
        if not session.pop('booked', False):
            return redirect(url_for('appointment'))
        return render_template('booking.html', title='Благодарим за доверието', success=True)

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        configured = db().execute('SELECT password FROM admin WHERE id=1').fetchone()
        if request.method == 'POST':
            blocked = limited('login:' + (request.remote_addr or ''), 10, 900)
            if not blocked and configured and check_password_hash(configured['password'], request.form.get('password', '')):
                session.clear()
                session['admin'] = True
                return redirect(url_for('admin'))
            flash('Невалидна парола или твърде много опити.', 'error')
        return render_template('login.html', title='Вход за екипа', configured=bool(configured))

    @app.post('/admin/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))

    @app.get('/admin')
    @admin_required
    def admin():
        status = request.args.get('status', '')
        rows = db().execute('SELECT * FROM bookings' + (' WHERE status=?' if status in STATUSES else '') + ' ORDER BY id DESC',
                            (status,) if status in STATUSES else ()).fetchall()
        counts = dict(db().execute('SELECT status,count(*) FROM bookings GROUP BY status').fetchall())
        return render_template('admin.html', title='Заявки за час', bookings=rows, counts=counts, selected=status)

    @app.post('/admin/bookings/<int:booking_id>')
    @admin_required
    def update_booking(booking_id):
        status = request.form.get('status')
        if status not in STATUSES:
            abort(400)
        db().execute('UPDATE bookings SET status=? WHERE id=?', (status, booking_id))
        db().commit()
        flash('Статусът е обновен.', 'success')
        return redirect(url_for('admin'))

    @app.route('/admin/content', methods=['GET', 'POST'])
    @admin_required
    def content():
        data = settings()
        if request.method == 'POST':
            for key in ('name', 'phone', 'email', 'address', 'hours', 'intro', 'description'):
                data[key] = request.form.get(key, '').strip()[:500]
            data['services'] = [{'name': n.strip()[:100], 'text': t.strip()[:500], 'price': p.strip()[:30], 'icon': f'{i+1:02}'}
                                for i, (n, t, p) in enumerate(zip(request.form.getlist('service_name'), request.form.getlist('service_text'), request.form.getlist('service_price'))) if n.strip()][:20]
            team_rows = [(i, n, r, b) for i, (n, r, b) in enumerate(zip(request.form.getlist('team_name'), request.form.getlist('team_role'), request.form.getlist('team_bio'))) if n.strip()][:12]
            data['team'] = [{'name': n.strip()[:100], 'role': r.strip()[:100], 'bio': b.strip()[:500], 'image': ''}
                            for i, n, r, b in team_rows]
            if not data['name'] or not data['services']:
                flash('Името на кабинета и поне една услуга са задължителни.', 'error')
                return redirect(url_for('content'))
            old = settings()
            try:
                data['hero'] = save_image(request.files.get('hero')) or old['hero']
                for i, member in enumerate(data['team']):
                    original_index = team_rows[i][0]
                    member['image'] = save_image(request.files.get(f'team_image_{original_index}')) or (old['team'][original_index]['image'] if original_index < len(old['team']) else '')
            except ValueError:
                flash('Снимката трябва да е JPEG, PNG или WebP до 5 MB и 16 мегапиксела.', 'error')
                return redirect(url_for('content'))
            db().execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(data, ensure_ascii=False),))
            db().commit()
            flash('Промените са запазени.', 'success')
            return redirect(url_for('content'))
        return render_template('content.html', title='Съдържание на сайта')

    def save_image(upload):
        if not upload or not upload.filename:
            return None
        from PIL import Image, ImageOps, UnidentifiedImageError
        try:
            photo = Image.open(upload.stream)
            if photo.format not in ('JPEG', 'PNG', 'WEBP') or photo.width * photo.height > 16_000_000:
                raise ValueError()
            photo.load()
            photo = ImageOps.exif_transpose(photo)
            photo.thumbnail((2000, 2000))
            folder = Path(app.instance_path) / 'uploads'
            folder.mkdir(exist_ok=True)
            name = secrets.token_hex(16) + '.webp'
            photo.convert('RGBA' if 'A' in photo.getbands() or 'transparency' in photo.info else 'RGB').save(folder / name, 'WEBP', quality=82, method=6)
            return '/media/' + name
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError() from exc

    @app.get('/media/<filename>')
    def media(filename):
        from flask import send_from_directory
        return send_from_directory(Path(app.instance_path) / 'uploads', filename, max_age=31536000)

    @app.get('/optimized-images/<filename>')
    def optimized_image(filename):
        from flask import send_from_directory
        if not re.fullmatch(r'[a-f0-9]{24}-(480|768|960|1280|1600|2000|[1-9][0-9]{0,3})\.webp', filename):
            abort(404)
        response = send_from_directory(Path(app.instance_path) / 'image-cache', filename, max_age=31536000)
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    @app.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nDisallow: /\n', mimetype='text/plain')

    @app.get('/sitemap.xml')
    def sitemap():
        from xml.etree.ElementTree import Element, SubElement, tostring
        root = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
        for path in ('/', '/services', '/team', '/prices', '/contact', '/appointment'):
            SubElement(SubElement(root, 'url'), 'loc').text = request.url_root.rstrip('/') + path
        return Response(tostring(root, encoding='utf-8', xml_declaration=True), mimetype='application/xml')

    @app.cli.command('set-admin')
    @click.password_option(confirmation_prompt=True)
    def set_admin(password):
        if len(password) < 12:
            raise click.ClickException('Използвайте поне 12 символа.')
        db().execute('INSERT OR REPLACE INTO admin VALUES (1, ?)', (generate_password_hash(password),))
        db().commit()
        click.echo('Администраторската парола е зададена.')

    @app.cli.command('demo-access')
    def demo_access():
        password = secrets.token_urlsafe(24)
        db().execute('INSERT OR REPLACE INTO admin VALUES (1, ?)', (generate_password_hash(password),))
        db().commit()
        access_file = Path(app.instance_path) / 'admin-access.txt'
        fd = os.open(access_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write('Локално демо: http://127.0.0.1:5057/admin\nПарола: ' + password + '\n')
        click.echo('Достъпът е записан в instance/admin-access.txt.')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('DENTAL_PORT', '5057')), debug=False)
