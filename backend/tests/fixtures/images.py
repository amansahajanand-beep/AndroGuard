import io

from PIL import Image


def raster_bytes(fmt: str, size: tuple[int, int] = (16, 16)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color=(20, 80, 160))
    image.save(buffer, format=fmt)
    return buffer.getvalue()
