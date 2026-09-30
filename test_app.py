import io
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import create_app


class DentalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'DATABASE': str(Path(self.tmp.name) / 'test.db')})
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def token(self, path):
        page = self.client.get(path).text
        return re.search(r'name="csrf_token" value="([^"]+)"', page)[1]

    def login(self):
        result = self.app.test_cli_runner().invoke(args=['set-admin', '--password', 'test-password-12345'])
        self.assertEqual(result.exit_code, 0, result.output)
        token = self.token('/admin/login')
        self.assertEqual(self.client.post('/admin/login', data={'csrf_token': token, 'password': 'wrong'}).status_code, 200)
        self.assertEqual(self.client.post('/admin/login', data={'csrf_token': token, 'password': 'test-password-12345'}).status_code, 302)

    def test_pages_and_access(self):
        for path in ['/', '/services', '/team', '/prices', '/contact', '/privacy', '/appointment', '/robots.txt', '/sitemap.xml']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.post('/appointment', data={}).status_code, 400)

    def test_booking_lifecycle(self):
        data = {'csrf_token': self.token('/appointment'), 'name': 'Тестов Пациент', 'phone': '0880000000',
                'day': (date.today()+timedelta(days=2)).isoformat(), 'period': '09:00–12:00',
                'patient': 'Нов пациент', 'service': 'Профилактика и преглед', 'consent': 'on'}
        invalid = self.client.post('/appointment', data={**data, 'day': '2020-01-01'})
        self.assertIn('Изберете дата', invalid.text)
        response = self.client.post('/appointment', data=data, follow_redirects=True)
        self.assertIn('Заявката е получена', response.text)
        self.login()
        self.assertIn('Тестов Пациент', self.client.get('/admin').text)
        token = self.token('/admin')
        self.client.post('/admin/bookings/1', data={'csrf_token': token, 'status': 'confirmed'})
        self.assertIn('Тестов Пациент', self.client.get('/admin?status=confirmed').text)
        self.assertNotIn('Тестов Пациент', self.client.get('/admin?status=new').text)

    def test_content_and_invalid_upload(self):
        self.login()
        data = {'csrf_token': self.token('/admin/content'), 'name': 'Тестово студио', 'phone': '',
                'address': 'Тестов адрес', 'service_name': ['Тестова услуга'], 'service_text': ['Описание'],
                'service_price': ['42'], 'team_name': ['Тестов член'], 'team_role': ['Роля'], 'team_bio': ['Био']}
        self.client.post('/admin/content', data=data)
        self.assertIn('Тестово студио', self.client.get('/').text)
        self.assertIn('42', self.client.get('/prices').text)
        from PIL import Image
        picture = io.BytesIO()
        Image.new('RGB', (30, 30), 'green').save(picture, 'PNG')
        picture.seek(0)
        data['hero'] = (picture, 'valid.png')
        self.client.post('/admin/content', data=data, content_type='multipart/form-data')
        homepage = self.client.get('/').text
        image_path = re.search(r'<img src="(/media/[^"]+)"', homepage)[1]
        with self.client.get(image_path) as image_response:
            self.assertEqual(image_response.status_code, 200)
        (Path(self.app.instance_path) / 'uploads' / image_path.rsplit('/', 1)[1]).unlink()
        data['hero'] = (io.BytesIO(b'not an image'), 'bad.jpg')
        response = self.client.post('/admin/content', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn('Снимката трябва', response.text)


if __name__ == '__main__':
    unittest.main()
