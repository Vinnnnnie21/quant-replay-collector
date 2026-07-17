from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PySide6 import QtCore, QtGui


WINDOWS_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _square_canvas(image: QtGui.QImage) -> QtGui.QImage:
    if image.width() == image.height():
        return image
    side = max(image.width(), image.height())
    canvas = QtGui.QImage(side, side, QtGui.QImage.Format_ARGB32)
    canvas.fill(image.pixelColor(0, 0))
    painter = QtGui.QPainter(canvas)
    painter.drawImage((side - image.width()) // 2, (side - image.height()) // 2, image)
    painter.end()
    return canvas


def _scaled_png(image: QtGui.QImage, size: int) -> bytes:
    scaled = image.scaled(
        size,
        size,
        QtCore.Qt.IgnoreAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    if not buffer.open(QtCore.QIODevice.WriteOnly) or not scaled.save(buffer, "PNG"):
        raise RuntimeError(f"Failed to encode {size}x{size} icon image")
    buffer.close()
    return bytes(data)


def build_windows_icon(
    source: Path,
    target: Path,
    *,
    sizes: tuple[int, ...] = WINDOWS_ICON_SIZES,
) -> Path:
    image = QtGui.QImage(str(source))
    if image.isNull():
        raise ValueError(f"Unreadable logo image: {source}")
    image = _square_canvas(image)

    blobs = [_scaled_png(image, size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries: list[bytes] = []
    for size, blob in zip(sizes, blobs):
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(blob),
                offset,
            )
        )
        offset += len(blob)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(header + b"".join(entries) + b"".join(blobs))
    temporary.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the multi-size QRC Windows icon")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_windows_icon(args.source.resolve(), args.output.resolve())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
