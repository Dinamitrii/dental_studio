"""Persistent responsive WebP copies; original images remain untouched."""
from functools import lru_cache
import hashlib
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

WIDTHS = (480, 768, 960, 1280, 1600, 2000)


def image_attributes(app, source):
    if source.startswith('/static/'):
        root, relative = Path(app.static_folder), source[len('/static/'):]
    elif source.startswith('/media/'):
        root, relative = Path(app.instance_path) / 'uploads', source[len('/media/'):]
    else:
        return {}
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return {}
    stat = path.stat()
    return _cached_attributes(str(path), str(Path(app.instance_path) / 'image-cache'), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=256)
def _cached_attributes(source, cache_folder, modified, size):
    path = Path(source)
    try:
        fingerprint = hashlib.sha256(path.read_bytes() + b'responsive-webp-v1').hexdigest()[:24]
        folder = Path(cache_folder)
        folder.mkdir(exist_ok=True)
        with Image.open(path) as original:
            if getattr(original, 'is_animated', False):
                return {}
            photo = ImageOps.exif_transpose(original)
            photo.load()
            photo = photo.convert('RGBA' if 'A' in photo.getbands() or 'transparency' in photo.info else 'RGB')
            width, height = photo.size
            variants = []
            for target in sorted({min(w, width) for w in WIDTHS}):
                name = f'{fingerprint}-{target}.webp'
                destination = folder / name
                if not destination.exists():
                    resized = photo.resize((target, max(1, round(height * target / width))), Image.Resampling.LANCZOS)
                    fd, temporary = tempfile.mkstemp(dir=folder, suffix='.webp')
                    os.close(fd)
                    try:
                        resized.save(temporary, 'WEBP', quality=82, method=6)
                        os.replace(temporary, destination)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                variants.append(f'/optimized-images/{name} {target}w')
            return {'srcset': ', '.join(variants), 'width': width, 'height': height}
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return {}
