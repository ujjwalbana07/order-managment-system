from io import BytesIO
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile


def prepare_image(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError('Choose an image smaller than 5 MB.')
    try:
        upload.seek(0)
        with Image.open(upload) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValidationError('Choose a JPEG, PNG or WebP image.')
            if source.width * source.height > 25000000:
                raise ValidationError('Choose an image smaller than 25 megapixels.')
            source.load()
            photo = ImageOps.exif_transpose(source).convert('RGB')
            photo.thumbnail((1600, 1600))
            output = BytesIO()
            photo.save(output, 'JPEG', quality=90)
            photo.thumbnail((240, 240))
            thumb = BytesIO()
            photo.save(thumb, 'JPEG', quality=85)
            name = uuid4().hex
            return ContentFile(output.getvalue(), name=f'{name}.jpg'), ContentFile(thumb.getvalue(), name=f'{name}-thumb.jpg')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError('This image could not be read. Choose a valid JPEG, PNG or WebP file.') from exc
