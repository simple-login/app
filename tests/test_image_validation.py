from app.image_validation import ImageFormat, detect_image_format
from pathlib import Path


def get_path_to_static_dir() -> Path:
    this_path = Path(__file__)
    repo_root_path = this_path.parent.parent
    return repo_root_path.joinpath("static")


def read_static_file_contents(filename: str) -> bytes:
    image_path = get_path_to_static_dir().joinpath(filename)
    with open(image_path.as_posix(), "rb") as f:
        return f.read()


def read_test_data_file_contents(filename: str) -> bytes:
    with open(f"./data/{filename}", "rb") as f:
        return f.read()


def test_non_image_file_returns_none():
    contents = read_static_file_contents("local-storage-polyfill.js")
    assert detect_image_format(contents) is ImageFormat.Unknown


def test_png_file_is_detected():
    contents = read_static_file_contents("logo.png")
    assert detect_image_format(contents) is ImageFormat.Png


def test_jpg_file_is_detected():
    contents = read_test_data_file_contents("1px.jpg")
    assert detect_image_format(contents) is ImageFormat.Jpg


def test_webp_file_is_detected():
    contents = read_test_data_file_contents("1px.webp")
    assert detect_image_format(contents) is ImageFormat.Webp


def test_svg_file_is_detected():
    contents = read_static_file_contents("icon.svg")
    assert detect_image_format(contents) is ImageFormat.Svg
