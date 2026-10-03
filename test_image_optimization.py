import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from image_optimization import image_attributes
from app import create_app


class ImageOptimizationTests(unittest.TestCase):
    def test_responsive_cache_transparency_and_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'uploads').mkdir()
            source = root / 'uploads' / 'portrait.png'
            Image.new('RGBA', (1000, 800), (0, 255, 0, 100)).save(source)
            app = SimpleNamespace(instance_path=temporary, static_folder=temporary)
            result = image_attributes(app, '/media/portrait.png')
            self.assertEqual((result['width'], result['height']), (1000, 800))
            self.assertIn('480w', result['srcset'])
            self.assertNotIn('1280w', result['srcset'])
            copies = list((root / 'image-cache').glob('*.webp'))
            times = {p: p.stat().st_mtime_ns for p in copies}
            self.assertEqual(result, image_attributes(app, '/media/portrait.png'))
            self.assertEqual(times, {p: p.stat().st_mtime_ns for p in copies})
            with Image.open(copies[0]) as image:
                self.assertEqual(image.mode, 'RGBA')
            Image.new('RGB', (640, 480), 'red').save(source)
            self.assertNotEqual(result['srcset'], image_attributes(app, '/media/portrait.png')['srcset'])
            self.assertEqual(image_attributes(app, '/media/../outside.png'), {})
            self.assertEqual(image_attributes(app, 'https://example.com/a.jpg'), {})

    def test_delivery_and_conditional_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'DATABASE': str(Path(temporary) / 'test.db')})
            client = app.test_client()
            page = client.get('/').text
            self.assertIn('srcset=', page)
            self.assertIn('loading="eager"', page)
            attributes = image_attributes(app, '/static/clinic.jpg')
            url = attributes['srcset'].split(', ')[0].split()[0]
            with client.get(url) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/webp')
                self.assertIn('immutable', response.headers['Cache-Control'])
                etag = response.headers['ETag']
                with Image.open(io.BytesIO(response.data)) as picture:
                    self.assertEqual(picture.width, 480)
            with client.get(url, headers={'If-None-Match': etag}) as response:
                self.assertEqual(response.status_code, 304)
            self.assertEqual(client.get('/optimized-images/invalid.webp').status_code, 404)
