"""Diagnostic pictures and publication for the bake REVIEW path."""
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image


REASON = 'اختلاف رندر MuPDF؛ ساختار اثبات‌شد؛ بازبینی انسانی لازم'


def _move(source, target):
    try:
        os.replace(source, target)
    except OSError as exc:
        if getattr(exc, 'winerror', None) != 17 and exc.errno != 18:
            raise
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.publish_', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        source.unlink()


def save_images(directory, page_number, before, after, diff):
    directory.mkdir(parents=True, exist_ok=True)
    images = {}
    for label, pixels in (('before', before), ('after', after), ('diff', diff)):
        name = f'bake_p{page_number:04d}_{label}.png'
        Image.fromarray(pixels).save(directory / name)
        images[label] = name
    return images


def publish_with_bake_review(pdf, output, pages):
    """Publish a QC-passed PDF only after its same-run pictures are in place."""
    review_pages = []
    images_to_move = []
    for page in pages:
        bake = page['bake']
        if not bake.get('review'):
            continue
        images = bake['review'].get('images', {})
        if images.keys() != {'before', 'after', 'diff'}:
            raise ValueError(f'Missing bake REVIEW images on input page {page["page"]}')
        paths = {}
        for label, name in images.items():
            if Path(name).name != name:
                raise ValueError('Invalid staged bake image name')
            relative = Path('review') / f'{pdf.stem}_{name}'
            images_to_move.append((pdf.parent / name, output / relative))
            paths[label] = relative.as_posix()
        review_pages.append({'page': page['page'], 'max_channel_difference': bake['max_channel_difference'],
                             'reason': bake['review']['reason'], 'images': paths})
    moved = []
    try:
        collisions = [target for _, target in images_to_move if target.exists()]
        if collisions:
            raise FileExistsError('Bake REVIEW evidence already exists: ' + ', '.join(p.name for p in collisions))
        for source, target in images_to_move:
            target.parent.mkdir(parents=True, exist_ok=True)
            _move(source, target)
            moved.append(target)
        _move(pdf, output / pdf.name)
    except BaseException:
        for target in moved:
            target.unlink(missing_ok=True)
        raise
    for entry in review_pages:
        pages[entry['page'] - 1]['bake']['review']['images'] = entry['images']
    return review_pages
