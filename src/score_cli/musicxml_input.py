"""Read uncompressed and compressed MusicXML scores."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class MusicXmlInputError(ValueError):
    """Raised when an input cannot be read as a MusicXML score."""


def read_musicxml(input_path: str | Path) -> str:
    """Return a validated MusicXML document from .musicxml, .xml, or .mxl."""

    path = Path(input_path)
    extension = path.suffix.lower()

    if extension == ".mxl":
        return _read_compressed_musicxml(path.read_bytes(), path)
    if extension not in {".musicxml", ".xml"}:
        shown_extension = extension or "(none)"
        raise MusicXmlInputError(
            f'Unsupported input extension "{shown_extension}"; '
            "expected .musicxml, .xml, or .mxl."
        )

    xml = _decode_xml(path.read_bytes())
    _assert_score_root(xml, str(path))
    return xml


def _read_compressed_musicxml(data: bytes, input_path: Path) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            entry_names = archive.namelist()
            score_name = _score_path_from_container(archive, entry_names)
            resolved_name = _resolve_score_entry(score_name, entry_names)
            if resolved_name is None:
                raise MusicXmlInputError(
                    f'Compressed MusicXML "{input_path}" contains no score XML file.'
                )
            xml = _decode_xml(archive.read(resolved_name))
    except BadZipFile as error:
        raise MusicXmlInputError(
            f'Cannot open compressed MusicXML "{input_path}": {error}'
        ) from error

    _assert_score_root(xml, f"{input_path}:{resolved_name}")
    return xml


def _score_path_from_container(archive: ZipFile, entry_names: list[str]) -> str | None:
    container_name = next(
        (name for name in entry_names if name.lower() == "meta-inf/container.xml"),
        None,
    )
    if container_name is None:
        return None

    try:
        container_root = ElementTree.fromstring(_decode_xml(archive.read(container_name)))
    except ElementTree.ParseError:
        return None

    rootfile = container_root.find(".//{*}rootfile")
    return rootfile.get("full-path") if rootfile is not None else None


def _resolve_score_entry(score_name: str | None, entry_names: list[str]) -> str | None:
    if score_name:
        for candidate in dict.fromkeys((score_name, unquote(score_name))):
            if candidate in entry_names:
                return candidate

    return next(
        (
            name
            for name in entry_names
            if not name.lower().startswith("meta-inf/")
            and name.lower().endswith((".musicxml", ".xml"))
        ),
        None,
    )


def _decode_xml(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def _assert_score_root(xml: str, source: str) -> None:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise MusicXmlInputError(f'Input "{source}" is not well-formed XML: {error}.') from error

    local_name = root.tag.rsplit("}", 1)[-1]
    if local_name not in {"score-partwise", "score-timewise"}:
        raise MusicXmlInputError(f'Input "{source}" is not a MusicXML score.')
