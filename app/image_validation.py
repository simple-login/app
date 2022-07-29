from enum import Enum


class ImageFormat(Enum):
    Png = 1
    Jpg = 2
    Webp = 3
    Unknown = 9


magic_numbers = {
    ImageFormat.Png: bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    ImageFormat.Jpg: bytes([0xFF, 0xD8, 0xFF, 0xE0]),
    ImageFormat.Webp: bytes([0x52, 0x49, 0x46, 0x46]),
}


def detect_image_format(image: bytes) -> ImageFormat:
    # Detect image based on magic number
    for fmt, header in magic_numbers.items():
        if image.startswith(header):
            return fmt

    # We don't know the type
    return ImageFormat.Unknown
