# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.frontend import OptionParser
from docutils.parsers.rst import Parser, roles
from docutils.utils import new_document


def dp_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    options = options or {}
    content = content or []
    node = nodes.inline(rawtext, text, **options)
    node["fls_id"] = text.strip()
    node["classes"].append("fls-paragraph-id")
    return [node], []


def p_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    options = options or {}
    content = content or []
    node = nodes.inline(rawtext, text)
    return [node], []


roles.register_local_role("dp", dp_role)
roles.register_local_role("p", p_role)


@dataclass
class ParagraphData:
    fls_id: str
    text: str
    section_id: str
    section_title: str
    section_path: str
    document: str
    document_title: str


@dataclass
class SectionData:
    section_id: str
    title: str
    path: str
    document: str
    document_title: str


def parse_spec(src_dir: Path) -> tuple[dict[str, ParagraphData], dict[str, SectionData]]:
    paragraphs: dict[str, ParagraphData] = {}
    sections: dict[str, SectionData] = {}

    for path in sorted(src_dir.rglob("*.rst")):
        document, document_title = parse_document(path)
        section_info = collect_sections(document, path.stem, document_title)
        sections.update(section_info)

        for paragraph in document.traverse(nodes.paragraph):
            dp_nodes = [
                node
                for node in paragraph.traverse(nodes.inline)
                if node.get("fls_id")
            ]
            if not dp_nodes:
                continue

            fls_id = dp_nodes[0].get("fls_id", "")
            if not fls_id:
                continue

            section = find_parent_of_type(paragraph, nodes.section)
            section_id = section_id_from_node(section)
            section_meta = sections.get(section_id)
            section_title = section_meta.title if section_meta else ""
            section_path = section_meta.path if section_meta else ""

            text = paragraph.astext().replace("\n", " ")
            text = strip_fls_id(text, fls_id)
            text = normalize_text(text)

            paragraphs[fls_id] = ParagraphData(
                fls_id=fls_id,
                text=text,
                section_id=section_id,
                section_title=section_title,
                section_path=section_path,
                document=path.stem,
                document_title=document_title,
            )

    return paragraphs, sections


def parse_document(path: Path) -> tuple[nodes.document, str]:
    text = path.read_text(encoding="utf-8")
    settings = OptionParser(components=(Parser,)).get_default_values()
    settings.report_level = 5
    settings.halt_level = 6
    settings.warning_stream = None
    settings.file_insertion_enabled = False

    document = new_document(str(path), settings)
    parser = Parser()
    parser.parse(text, document)

    title_node = document.next_node(nodes.title)
    document_title = title_node.astext() if title_node else path.stem
    return document, document_title


def collect_sections(
    document: nodes.document,
    docname: str,
    document_title: str,
) -> dict[str, SectionData]:
    sections: dict[str, SectionData] = {}

    def walk(node: nodes.Node, path_prefix: list[int]) -> None:
        index = 0
        for child in node.children:
            if not isinstance(child, nodes.section):
                continue
            index += 1
            path = path_prefix + [index]
            section_id = section_id_from_node(child)
            title = section_title_from_node(child)
            path_str = ".".join(str(part) for part in path)
            if section_id:
                sections[section_id] = SectionData(
                    section_id=section_id,
                    title=title,
                    path=path_str,
                    document=docname,
                    document_title=document_title,
                )
            walk(child, path)

    walk(document, [])
    return sections


def section_title_from_node(section: nodes.section | None) -> str:
    if section is None:
        return ""
    for child in section.children:
        if isinstance(child, nodes.title):
            return child.astext()
    return ""


def section_id_from_node(section: nodes.section | None) -> str:
    if section is None:
        return ""
    names = section.get("names", [])
    for name in names:
        if name.startswith("fls_"):
            return name
    return ""


def find_parent_of_type(node: nodes.Node, node_type: type[nodes.Node]) -> Any:
    cursor = node
    while cursor is not None:
        if isinstance(cursor, node_type):
            return cursor
        cursor = cursor.parent
    return None


def strip_fls_id(text: str, fls_id: str) -> str:
    if text.startswith(fls_id):
        return text[len(fls_id) :].lstrip()
    return text.replace(fls_id, "", 1).strip()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\[\s+", "[", text)
    text = re.sub(r"\s+\]", "]", text)
    return text
