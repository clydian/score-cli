"""Snapshot-bound structural operations and a lossless semantic disposition ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lxml import etree as ET

from .score_document import (
    ScoreDocument,
    ScoreError,
    name,
    child,
    children,
    make,
    content,
    replace_note_children,
)

OPERATIONS = {
    "insert-event",
    "delete-event",
    "replace-measure",
    "insert-measure",
    "delete-measure",
    "renumber-measures",
    "rename-part",
    "reorder-parts",
    "add-part",
    "delete-part",
    "merge-part",
}


def xml(element):
    return ET.tostring(element, encoding="unicode", with_tail=False)


def fragment(value):
    if not isinstance(value, str):
        raise ScoreError(
            "invalid-xml-fragment", "Expected an explicit XML fragment string."
        )
    try:
        wrapper = ET.fromstring(
            ("<fragment>" + value + "</fragment>").encode(),
            ET.XMLParser(resolve_entities=False, no_network=True),
        )
        if (
            len(wrapper) != 1
            or (wrapper.text or "").strip()
            or (wrapper[0].tail or "").strip()
        ):
            raise ScoreError(
                "invalid-xml-fragment", "Expected exactly one XML subtree."
            )
        element = (
            ET.fromstring(
                ET.tostring(wrapper[0]),
                ET.XMLParser(resolve_entities=False, no_network=True),
            )
            if isinstance(wrapper[0].tag, str)
            else wrapper[0]
        )
    except ET.XMLSyntaxError as exc:
        raise ScoreError("invalid-xml-fragment", str(exc)) from exc
    if b"<!DOCTYPE" in value.encode() or any(
        isinstance(e, ET._Entity) for e in element.iter()
    ):
        raise ScoreError(
            "unsupported-entity", "Fragment DTDs and entity references are unsupported."
        )
    if any(
        isinstance(e.tag, str) and ET.QName(e).localname in {"image", "link"}
        for e in element.iter()
    ):
        raise ScoreError(
            "unsupported-resource", "Linked resources cannot be preserved."
        )
    return element


def semantics(element):
    # Preserve namespace meaning, comments, PIs, and significant text; ignore formatting.
    tag = (
        element.tag
        if isinstance(element.tag, str)
        else (
            "pi:" + str(element.target)
            if isinstance(element, ET._ProcessingInstruction)
            else "comment"
        )
    )
    return (
        tag,
        sorted(element.attrib.items()),
        (element.text or "").strip(),
        tuple((semantics(e), (e.tail or "").strip()) for e in element),
    )


@dataclass
class Reference:
    name: str


class StructureTransaction:
    def __init__(self, document: ScoreDocument):
        self.document = document
        self.bindings: dict[str, Any] = {}
        self.declared: set[str] = set()
        self.ledger: list[dict] = []
        self.original_measures = list(document.measures())
        self.merge_destinations: dict = {}
        self.original_events = list(document.events())

    def note(self, target):
        if isinstance(target, dict) and set(target) == {"ref"}:
            if target["ref"] not in self.declared:
                raise ScoreError(
                    "invalid-reference", "Only an earlier creation can be referenced."
                )
            return Reference(target["ref"])
        return self.document.locate(target)

    def live_direction(self, target):
        if any(e is target.element for e in self.document.root.iter()):
            return target
        if target.insertion_index is None:
            raise ScoreError(
                "detached-target", "Direction was removed earlier in this transaction."
            )
        self.live(target.measure)
        if target.element.getparent() is not None:
            raise ScoreError(
                "detached-target",
                "Direction was removed with its containing structure.",
            )
        # Virtual directions are anchored at musical offset zero, never a drifting child index.
        index = 0
        for i, element in enumerate(target.measure):
            if name(element) in {"note", "backup", "forward"}:
                break
            if name(element) == "attributes":
                index = i + 1
        target.insertion_index = index
        return target

    def live_note(self, target):
        element = (
            self.bindings[target.name]
            if isinstance(target, Reference)
            else target.element
        )
        found = [e for e in self.document.events() if e.element is element]
        if len(found) != 1:
            raise ScoreError(
                "detached-target",
                "Target was removed or replaced earlier in this transaction.",
            )
        return found[0]

    def resolve(self, operation):
        allowed = {"id", "type", "target", "expected", "value", "discard"}
        extras = {
            "insert-event": {"position", "timeline", "inherit", "bind", "bindings"},
            "delete-event": {"timeline"},
            "replace-measure": {"bind", "bindings"},
            "insert-measure": {"position", "inherit", "bind", "bindings"},
            "add-part": {"position", "bind", "bindings"},
        }
        if not set(operation) <= allowed | extras.get(
            operation["type"], set()
        ) or not isinstance(operation.get("target"), dict):
            raise ScoreError(
                "invalid-operation", "Unsupported structural fields or target shape."
            )
        if operation["type"] == "merge-part" and (
            not isinstance(operation["value"], dict)
            or not isinstance(operation["value"].get("measures"), dict)
        ):
            raise ScoreError(
                "invalid-mapping", "Merge requires an explicit measures mapping."
            )
        target: Any
        if operation["type"] == "merge-part":
            selector = operation["target"]
            if (
                set(selector) != {"sourcePartId", "targetPartId"}
                or selector["sourcePartId"] == selector["targetPartId"]
            ):
                raise ScoreError(
                    "invalid-merge", "Choose distinct explicit source and target parts."
                )
            pairs = [
                (
                    self.measure(
                        {"partId": selector["sourcePartId"], "printedMeasure": a}
                    ),
                    self.measure(
                        {"partId": selector["targetPartId"], "printedMeasure": b}
                    ),
                )
                for a, b in operation["value"]["measures"].items()
            ]
            target = (
                self.part({"partId": selector["sourcePartId"]}),
                self.part({"partId": selector["targetPartId"]}),
                pairs,
            )
        elif operation["type"] in {"rename-part", "add-part", "delete-part"}:
            target = self.part(operation["target"])
        elif operation["type"] == "reorder-parts":
            target = [child(self.document.root, "part-list")]
        elif operation["type"] in {"insert-measure", "delete-measure"}:
            target = (
                self.note(operation["target"])
                if set(operation["target"]) == {"ref"}
                else self.logical(operation["target"]["printedMeasure"])
            )
        elif operation["type"] == "renumber-measures":
            labels = operation["target"]["printedMeasures"]
            if (
                not isinstance(labels, list)
                or len(set(labels)) != len(labels)
                or not labels
            ):
                raise ScoreError(
                    "invalid-mapping",
                    "Expected unique printedMeasures in explicit order.",
                )
            target = [self.logical(label) for label in labels]
        elif operation["type"] == "insert-event" and operation.get("position") in {
            "start",
            "end",
        }:
            target = self.measure(operation["target"])
        elif operation["type"] == "replace-measure":
            target = self.measure(operation["target"])
        else:
            target = self.note(operation["target"])
        binding = operation.get("bind")
        nested = operation.get("bindings", {})
        if not isinstance(nested, dict) or not all(
            isinstance(v, str) and v for v in nested.values()
        ):
            raise ScoreError(
                "invalid-reference",
                "bindings maps reference names to explicit XML IDs in newly provided content.",
            )
        declarations = ([binding] if binding is not None else []) + list(nested)
        if declarations and operation["type"] not in {
            "insert-event",
            "insert-measure",
            "add-part",
            "replace-measure",
        }:
            raise ScoreError(
                "invalid-reference", "Only creation operations can bind new objects."
            )
        for binding in declarations:
            if not isinstance(binding, str) or not binding or binding in self.declared:
                raise ScoreError(
                    "invalid-reference",
                    "Creation bindings must be unique nonempty strings.",
                )
            self.declared.add(binding)
        return target

    def bind_created(self, operation, roots, *, single=False):
        if "bind" in operation:
            self.bindings[operation["bind"]] = roots[0] if single else roots
        for reference, identity in operation.get("bindings", {}).items():
            matches = [
                e for root in roots for e in root.iter() if e.get("id") == identity
            ]
            if len(matches) != 1:
                raise ScoreError(
                    "invalid-reference",
                    "XML ID binding must select exactly one newly supplied object.",
                )
            self.bindings[reference] = matches[0]

    def selection(self, target, kind):
        values = self.bindings[target.name] if isinstance(target, Reference) else target
        if not isinstance(values, list):
            raise ScoreError("reference-kind", "Expected a collection reference.")
        elements = [self.live(e) for e in values]
        if not elements:
            raise ScoreError("reference-kind", "Empty structural collection.")
        if kind == "part":
            if (
                name(elements[0]) != "score-part"
                or self.part({"partId": elements[0].get("id")}) != elements
            ):
                raise ScoreError(
                    "reference-kind",
                    "Expected one part definition and all of its native bodies.",
                )
        elif kind == "logical":
            if (
                any(name(e) != "measure" for e in elements)
                or len({e.get("number") for e in elements}) != 1
                or self.logical(elements[0].get("number")) != elements
            ):
                raise ScoreError(
                    "reference-kind",
                    "Expected exactly one logical measure across all current parts.",
                )
        elif kind == "part-list" and (
            len(elements) != 1
            or elements[0] is not child(self.document.root, "part-list")
        ):
            raise ScoreError("reference-kind", "Expected the current part-list.")
        return elements

    def merge(self, operation, target):
        source = [self.live(e) for e in target[0]]
        destination = [self.live(e) for e in target[1]]
        self.check(operation, source + destination)
        value = operation["value"]
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "measures",
                "voices",
                "staves",
                "instruments",
                "destination",
                "sourceDisposition",
                "wrapperPolicy",
                "contextPolicy",
            }
            or value["destination"] != "replace"
            or value["sourceDisposition"] != "delete-part"
            or value["wrapperPolicy"] != "keep-target"
            or value["contextPolicy"] != "require-equal"
        ):
            raise ScoreError(
                "explicit-policy-required",
                "Merge requires explicit maps and replace/delete-part/keep-target/require-equal policies.",
            )
        for key in ("measures", "voices", "staves", "instruments"):
            mapping = value[key]
            if (
                not isinstance(mapping, dict)
                or not all(
                    isinstance(k, str) and k and isinstance(v, str) and v
                    for k, v in mapping.items()
                )
                or len(set(mapping.values())) != len(mapping)
            ):
                raise ScoreError(
                    "invalid-mapping",
                    "Merge maps must be explicit, unambiguous string mappings.",
                )
        if not value["measures"]:
            raise ScoreError(
                "invalid-mapping", "At least one source measure is required."
            )
        source_id, destination_id = source[0].get("id"), destination[0].get("id")
        pairs = [(self.live(a), self.live(b)) for a, b in target[2]]
        selected = {a for a, _ in pairs}
        source_measures = [
            e for p, _, _, e, _ in self.document.measures() if p == source_id
        ]
        outer_content = []
        if name(self.document.root) == "score-partwise":
            outer_content = [
                e
                for body in source[1:]
                for e in body
                if e not in children(body, "measure")
            ]
        if any(
            (e.text or "").strip() or (e.tail or "").strip()
            for e in source[1:] + source_measures
        ):
            raise ScoreError(
                "unsupported-mixed-content",
                "Source wrappers contain significant text; preserve the enclosing structure explicitly.",
            )
        removed = (
            [source[0]]
            + outer_content
            + [e for m in source_measures if m not in selected for e in m]
            + [e for _, m in pairs for e in m]
        )
        self.discard(operation, removed)
        deleted = [xml(e) for e in removed]
        moved = [xml(e) for m, _ in pairs for e in m]
        original_events = [
            e for e in self.document.events() if e.element.getparent() in selected
        ]
        target_instruments = {
            e.get("id") for e in children(destination[0], "score-instrument")
        }
        if not set(value["instruments"].values()) <= target_instruments:
            raise ScoreError(
                "invalid-instrument-reference",
                "Instrument targets must be declared in the destination part.",
            )
        for event in original_events:
            for key, plural in [("voice", "voices"), ("staff", "staves")]:
                old = content(event.element, key, "1")
                if old not in value[plural]:
                    raise ScoreError(
                        "incomplete-mapping",
                        "Every source note voice/staff requires an explicit rule.",
                    )
        for source_measure, destination_measure in pairs:
            for e in list(destination_measure):
                destination_measure.remove(e)
            for e in list(source_measure):
                destination_measure.append(e)
                for item in e.iter():
                    tag = name(item)
                    if tag == "note":
                        for key, plural in [("voice", "voices"), ("staff", "staves")]:
                            old = content(item, key, "1")
                            new = value[plural][old]
                            if old != new:
                                replace_note_children(item, key, [make(item, key, new)])
                    elif tag in {"voice", "staff"} and name(item.getparent()) != "note":
                        rules = value["voices" if tag == "voice" else "staves"]
                        if item.text not in rules:
                            raise ScoreError(
                                "incomplete-mapping",
                                "Non-note voice/staff requires an explicit rule.",
                            )
                        item.text = rules[item.text]
                    if tag in {
                        "instrument",
                        "midi-instrument",
                        "midi-device",
                    } and item.get("id"):
                        old_id = item.get("id")
                        if old_id not in value["instruments"]:
                            raise ScoreError(
                                "incomplete-mapping",
                                "Every instrument reference requires an explicit rule.",
                            )
                        item.set("id", value["instruments"][old_id])
            self.merge_destinations[source_measure] = destination_measure
        for e in source:
            e.getparent().remove(e)
        after_events = {e.element: e for e in self.document.events()}
        for old_event in original_events:
            new_event = after_events[old_event.element]
            if (
                old_event.context != new_event.context
                or old_event.offset != new_event.offset
                or old_event.duration != new_event.duration
            ):
                raise ScoreError(
                    "merge-context-conflict",
                    "Moved music has different inherited context or timeline; explicitly prepare compatible measure attributes first.",
                )
        self.ledger.append(
            dict(
                operationId=operation["id"],
                added=[],
                preserved=[],
                moved=moved,
                deleted=deleted,
                consumedWrappers=[xml(e) for e in source],
                rules=value,
            )
        )

    def part(self, target):
        if set(target) == {"ref"}:
            return self.note(target)
        if set(target) != {"partId"} or not isinstance(target["partId"], str):
            raise ScoreError("invalid-locator", "Part target requires exact partId.")
        part_list = child(self.document.root, "part-list")
        if part_list is None:
            raise ScoreError("part-structure", "Missing part-list.")
        definitions = [
            e
            for e in children(part_list, "score-part")
            if e.get("id") == target["partId"]
        ]
        if len(definitions) != 1:
            raise ScoreError("ambiguous-part", "Expected one part definition.")
        if name(self.document.root) == "score-partwise":
            content_parts = [
                p
                for p in children(self.document.root, "part")
                if p.get("id") == target["partId"]
            ]
            if len(content_parts) != 1:
                raise ScoreError("part-structure", "Expected one part body.")
        else:
            content_parts = [
                e for p, _, _, e, _ in self.document.measures() if p == target["partId"]
            ]
            if len(content_parts) != len(children(self.document.root, "measure")):
                raise ScoreError(
                    "part-structure", "Expected one body per timewise measure."
                )
        return definitions + content_parts

    def part_edit(self, operation, target):
        elements = self.selection(
            target, "part-list" if operation["type"] == "reorder-parts" else "part"
        )
        self.check(operation, elements)
        kind = operation["type"]
        value = operation["value"]
        if kind == "reorder-parts":
            new = fragment(value)
            old_ids = [p.get("id", "") for p in children(elements[0], "score-part")]
            new_ids = [p.get("id", "") for p in children(new, "score-part")]
            if sorted(old_ids) != sorted(new_ids):
                raise ScoreError(
                    "part-structure", "Reorder must contain exactly the existing parts."
                )
            for old_part in children(elements[0], "score-part"):
                corresponding = next(
                    p
                    for p in children(new, "score-part")
                    if p.get("id") == old_part.get("id")
                )
                if semantics(old_part) != semantics(corresponding):
                    raise ScoreError(
                        "replacement-boundary",
                        "Reorder cannot change part definitions.",
                    )
            self.replacement(operation, elements[0], new)
            parents = (
                [self.document.root]
                if name(self.document.root) == "score-partwise"
                else children(self.document.root, "measure")
            )
            for parent in parents:
                parts = children(parent, "part")
                slots = [parent.index(p) for p in parts]
                by_id = {p.get("id"): p for p in parts}
                for p in parts:
                    parent.remove(p)
                for slot, identity in zip(slots, new_ids):
                    parent.insert(slot, by_id[identity])
            return
        definition = elements[0]
        part_list = definition.getparent()
        if kind == "delete-part":
            if value is not None:
                raise ScoreError("invalid-operation", "Deletion value must be null.")
            self.discard(operation, elements)
            old = [xml(e) for e in elements]
            for e in elements:
                e.getparent().remove(e)
            self.ledger.append(
                dict(
                    operationId=operation["id"],
                    added=[],
                    preserved=[],
                    moved=[],
                    deleted=old,
                )
            )
            return
        if kind == "rename-part":
            if (
                not isinstance(value, dict)
                or set(value) != {"id", "name", "instruments"}
                or not all(
                    isinstance(value[k], str) and value[k] for k in ("id", "name")
                )
            ):
                raise ScoreError(
                    "invalid-part",
                    "Rename requires id, name and explicit instruments mapping.",
                )
            if any(
                p is not definition and p.get("id") == value["id"]
                for p in children(part_list, "score-part")
            ):
                raise ScoreError("part-collision", "Part ID already exists.")
            mapping = value["instruments"]
            instruments = children(definition, "score-instrument")
            known = {e.get("id") for e in instruments}
            if (
                not isinstance(mapping, dict)
                or not set(mapping) <= known
                or not all(isinstance(v, str) and v for v in mapping.values())
            ):
                raise ScoreError(
                    "invalid-mapping",
                    "Instrument mapping keys must be existing declarations.",
                )
            final = [
                mapping.get(e.get("id"), e.get("id"))
                for p in children(part_list, "score-part")
                for e in children(p, "score-instrument")
            ]
            if len(final) != len(set(final)):
                raise ScoreError(
                    "instrument-collision", "Instrument IDs must stay unique."
                )
            old = [xml(e) for e in elements]
            for e in elements:
                e.set("id", value["id"])
                for descendant in e.iter():
                    if (
                        name(descendant)
                        in {
                            "score-instrument",
                            "midi-instrument",
                            "midi-device",
                            "instrument",
                        }
                        and descendant.get("id") in mapping
                    ):
                        descendant.set("id", mapping[descendant.get("id")])
            part_name = child(definition, "part-name")
            if part_name is None or len(part_name):
                raise ScoreError(
                    "unsupported-part-name", "Expected a plain existing part-name."
                )
            part_name.text = value["name"]
            self.ledger.append(
                dict(
                    operationId=operation["id"],
                    added=[],
                    preserved=[],
                    moved=old,
                    deleted=[],
                    value=value,
                )
            )
            return
        if (
            not isinstance(value, dict)
            or set(value) != {"definition", "content"}
            or not isinstance(value["content"], list)
        ):
            raise ScoreError(
                "invalid-part",
                "Add requires definition and complete native content array.",
            )
        new_definition = fragment(value["definition"])
        new_parts = [fragment(s) for s in value["content"]]
        identity = new_definition.get("id")
        if (
            new_definition.tag != definition.tag
            or not identity
            or any(p.get("id") == identity for p in children(part_list, "score-part"))
        ):
            raise ScoreError("part-collision", "New definition needs a unique part ID.")
        if len(new_parts) != len(elements) - 1 or any(
            p.get("id") != identity or p.tag != anchor.tag
            for p, anchor in zip(new_parts, elements[1:])
        ):
            raise ScoreError(
                "part-structure", "Provide every native body with the new part ID."
            )
        if operation.get("position") not in {"before", "after"}:
            raise ScoreError("invalid-anchor", "Position must be before or after.")
        for anchor, new_part in zip(elements, [new_definition] + new_parts):
            parent = anchor.getparent()
            parent.insert(
                parent.index(anchor) + (operation["position"] == "after"), new_part
            )
        self.bind_created(operation, [new_definition] + new_parts)
        self.ledger.append(
            dict(
                operationId=operation["id"],
                added=[xml(e) for e in [new_definition] + new_parts],
                preserved=[xml(e) for e in elements],
                moved=[],
                deleted=[],
            )
        )

    def logical(self, label):
        if not isinstance(label, str) or not label:
            raise ScoreError(
                "invalid-locator", "Printed measure must be an exact nonempty string."
            )
        matches = [row for row in self.document.measures() if row[1] == label]
        part_list = child(self.document.root, "part-list")
        if part_list is None:
            raise ScoreError("part-structure", "Missing part-list.")
        part_ids = [e.get("id", "") for e in children(part_list, "score-part")]
        if sorted(p for p, *_ in matches) != sorted(part_ids):
            raise ScoreError(
                "ambiguous-measure",
                "Logical measure must occur exactly once in every part.",
            )
        result = []
        for _, _, _, _, wrapper in matches:
            if wrapper not in result:
                result.append(wrapper)
        return result

    def logical_edit(self, operation, target):
        kind = operation["type"]
        if kind == "renumber-measures":
            elements = [e for group in target for e in self.selection(group, "logical")]
            self.check(operation, elements)
            mapping = operation["value"]
            labels = [group[0].get("number") for group in target]
            if (
                not isinstance(mapping, dict)
                or set(mapping) != set(labels)
                or not all(isinstance(v, str) and v for v in mapping.values())
            ):
                raise ScoreError(
                    "invalid-mapping",
                    "Mapping must cover exactly the current selected labels with string values.",
                )
            current = [
                row[1]
                for row in self.document.measures()
                if row[0] == self.document.measures()[0][0]
            ]
            updated = [mapping.get(label, label) for label in current]
            if len(set(updated)) != len(updated):
                raise ScoreError(
                    "mapping-collision",
                    "Renumbering would create duplicate printed numbers.",
                )
            old = [xml(e) for e in elements]
            for group, label in zip(target, labels):
                for e in group:
                    e.set("number", mapping[label])
            self.ledger.append(
                dict(
                    operationId=operation["id"],
                    added=[],
                    preserved=[],
                    moved=old,
                    deleted=[],
                    mapping=mapping,
                )
            )
            return
        elements = self.selection(target, "logical")
        self.check(operation, elements)
        if kind == "delete-measure":
            if operation["value"] is not None:
                raise ScoreError("invalid-operation", "Deletion value must be null.")
            self.discard(operation, elements)
            old = [xml(e) for e in elements]
            for e in elements:
                e.getparent().remove(e)
            self.ledger.append(
                dict(
                    operationId=operation["id"],
                    added=[],
                    preserved=[],
                    moved=[],
                    deleted=old,
                )
            )
            return
        if (
            operation.get("position") not in {"before", "after"}
            or operation.get("inherit") != "effective-context"
        ):
            raise ScoreError(
                "explicit-policy-required",
                "Insert requires before/after and inherit=effective-context.",
            )
        value = operation["value"]
        if name(self.document.root) == "score-timewise":
            new_elements = [fragment(value)]
            if new_elements[0].tag != elements[0].tag:
                raise ScoreError(
                    "invalid-measure", "Provide a complete native measure wrapper."
                )
            expected_ids = [p.get("id") for p in children(elements[0], "part")]
            if [p.get("id") for p in children(new_elements[0], "part")] != expected_ids:
                raise ScoreError(
                    "part-structure",
                    "Inserted timewise measure must explicitly contain every part in order.",
                )
        else:
            ids = [e.getparent().get("id") for e in elements]
            if not isinstance(value, dict) or set(value) != set(ids):
                raise ScoreError(
                    "part-structure", "Explicit content is required for every part."
                )
            new_elements = [fragment(value[p]) for p in ids]
        inserted_labels = {e.get("number") for e in new_elements}
        if (
            len(inserted_labels) != 1
            or not next(iter(inserted_labels))
            or any(row[1] in inserted_labels for row in self.document.measures())
        ):
            raise ScoreError(
                "mapping-collision",
                "Inserted number must be new and identical in every part.",
            )
        for anchor, new in zip(elements, new_elements):
            if anchor.tag != new.tag:
                raise ScoreError(
                    "invalid-measure",
                    "Inserted wrapper must match the native score namespace.",
                )
            parent = anchor.getparent()
            parent.insert(
                parent.index(anchor) + (operation["position"] == "after"), new
            )
        self.bind_created(operation, new_elements)
        self.ledger.append(
            dict(
                operationId=operation["id"],
                added=[xml(e) for e in new_elements],
                preserved=[xml(e) for e in elements],
                moved=[],
                deleted=[],
            )
        )

    def measure(self, target):
        if set(target) == {"ref"}:
            return self.note(target)
        if set(target) != {"partId", "printedMeasure"} or not all(
            isinstance(v, str) for v in target.values()
        ):
            raise ScoreError(
                "invalid-locator",
                "Measure requires exact partId and printedMeasure strings.",
            )
        matches = [
            e
            for p, m, _, e, _ in self.document.measures()
            if p == target["partId"] and m == target["printedMeasure"]
        ]
        if len(matches) != 1:
            raise ScoreError("ambiguous-measure", "Expected exactly one part-measure.")
        return matches[0]

    def live(self, target):
        element = (
            self.bindings[target.name] if isinstance(target, Reference) else target
        )
        if not any(e is element for e in self.document.root.iter()):
            raise ScoreError(
                "detached-target", "Target was removed earlier in this transaction."
            )
        return element

    def check(self, operation, elements):
        expected = operation["expected"]
        if not isinstance(expected, list) or [
            semantics(fragment(s)) for s in expected
        ] != [semantics(e) for e in elements]:
            raise ScoreError(
                "old-value-mismatch", "Expected XML differs from current target."
            )

    def replacement(self, operation, target, new):
        if (
            target.tag != new.tag
            or dict(target.attrib) != dict(new.attrib)
            or (target.text or "").strip() != (new.text or "").strip()
        ):
            raise ScoreError(
                "replacement-boundary",
                "Replacement must retain wrapper identity and attributes.",
            )
        available = list(target)
        contents = []
        kept = []
        for item in new:
            match = next(
                (
                    e
                    for e in available
                    if semantics(e) == semantics(item)
                    and (e.tail or "").strip() == (item.tail or "").strip()
                ),
                None,
            )
            if match is not None:
                available.remove(match)
                kept.append(xml(match))
                contents.append(match)
            else:
                contents.append(item)
        self.discard(operation, available)
        deleted = [xml(e) for e in available]
        added = [xml(e) for e in contents if e.getparent() is not target]
        for e in list(target):
            target.remove(e)
        target.extend(contents)
        self.bind_created(operation, [target], single=True)
        self.ledger.append(
            dict(
                operationId=operation["id"],
                added=added,
                preserved=kept,
                moved=[],
                deleted=deleted,
            )
        )

    def apply(self, operation, target):
        if operation["type"] == "merge-part":
            self.merge(operation, target)
            return
        if operation["type"] in {
            "rename-part",
            "reorder-parts",
            "add-part",
            "delete-part",
        }:
            self.part_edit(operation, target)
            return
        if operation["type"] in {
            "insert-measure",
            "delete-measure",
            "renumber-measures",
        }:
            self.logical_edit(operation, target)
            return
        if operation["type"] == "replace-measure":
            element = self.live(target)
            if not any(e is element for _, _, _, e, _ in self.document.measures()):
                raise ScoreError(
                    "reference-kind", "Replacement target must be a part-measure."
                )
            self.check(operation, [element])
            self.replacement(operation, element, fragment(operation["value"]))
            return
        edge = operation["type"] == "insert-event" and operation.get("position") in {
            "start",
            "end",
        }
        anchor = self.live(target) if edge else self.live_note(target).element
        expected = operation["expected"]
        if (
            not isinstance(expected, list)
            or len(expected) != 1
            or semantics(fragment(expected[0])) != semantics(anchor)
        ):
            raise ScoreError(
                "old-value-mismatch", "Expected XML differs from current target."
            )
        if operation["type"] == "delete-event":
            if (
                operation["value"] is not None
                or operation.get("timeline") != "shift-following"
            ):
                raise ScoreError(
                    "explicit-policy-required",
                    "Delete requires value=null and timeline=shift-following.",
                )
            self.discard(operation, [anchor])
            anchor.getparent().remove(anchor)
            self.ledger.append(
                dict(
                    operationId=operation["id"],
                    added=[],
                    preserved=[],
                    moved=[],
                    deleted=[xml(anchor)],
                )
            )
            return
        if (
            operation.get("timeline") != "shift-following"
            or operation.get("inherit") != "effective-context"
        ):
            raise ScoreError(
                "explicit-policy-required",
                "Insert requires timeline=shift-following and inherit=effective-context.",
            )
        if operation.get("position") not in {"before", "after", "start", "end"}:
            raise ScoreError(
                "invalid-anchor", "Position must select an exact note or measure edge."
            )
        new = fragment(operation["value"])
        expected_tag = make(anchor, "note").tag if edge else anchor.tag
        if new.tag != expected_tag:
            raise ScoreError(
                "invalid-note", "Inserted XML must be a note in the score namespace."
            )
        self.discard(operation, [])
        if edge:
            if not any(e is anchor for _, _, _, e, _ in self.document.measures()):
                raise ScoreError(
                    "reference-kind", "Edge anchor must refer to a part-measure."
                )
            index = len(anchor) if operation["position"] == "end" else 0
            anchor.insert(index, new)
        else:
            parent = anchor.getparent()
            parent.insert(
                parent.index(anchor) + (operation["position"] == "after"), new
            )
        self.bind_created(operation, [new], single=True)
        self.ledger.append(
            dict(
                operationId=operation["id"],
                added=[xml(new)],
                preserved=[xml(anchor)],
                moved=[],
                deleted=[],
            )
        )

    def discard(self, operation, removed):
        if any((e.tail or "").strip() for e in removed):
            raise ScoreError(
                "unsupported-mixed-content",
                "Significant sibling tail text requires replacing its enclosing element.",
            )
        declared = operation.get("discard", [])
        if not isinstance(declared, list) or sorted(
            repr(semantics(fragment(s))) for s in declared
        ) != sorted(repr(semantics(e)) for e in removed):
            raise ScoreError(
                "undeclared-semantic-deletion",
                "Every removed XML subtree must appear exactly once in discard.",
            )

    def diagnostic_baseline(self, diagnostics):
        if not self.ledger:
            return diagnostics
        current_measures = {
            e: dict(partId=p, printedMeasure=m, measureOrdinal=o)
            for p, m, o, e, _ in self.document.measures()
        }
        current_events = {
            e.element: dict(e.location, measureOrdinal=e.measure_ordinal)
            for e in self.document.events()
        }
        result = []
        for diagnostic in diagnostics:
            old = diagnostic["location"]
            matches = [
                e
                for p, m, _, e, _ in self.original_measures
                if p == old.get("partId") and m == old.get("printedMeasure")
            ]
            mapped = None
            if len(matches) == 1:
                if "eventIndex" in old:
                    events = [
                        e
                        for e in self.original_events
                        if e.location["partId"] == old["partId"]
                        and e.location["printedMeasure"] == old["printedMeasure"]
                        and e.location["eventIndex"] == old["eventIndex"]
                    ]
                    if len(events) == 1:
                        mapped = current_events.get(events[0].element)
                else:
                    mapped = current_measures.get(
                        self.merge_destinations.get(matches[0], matches[0])
                    )
                if mapped is None:
                    continue
            elif old.get("printedMeasure") is not None:
                continue
            if mapped is not None:
                old = {k: mapped.get(k, v) for k, v in old.items()}
            result.append(dict(diagnostic, location=old))
        return result

    def report(self):
        current = {
            e: dict(partId=p, printedMeasure=m)
            for p, m, _, e, _ in self.document.measures()
        }
        rows = [
            dict(
                before=dict(partId=p, printedMeasure=m),
                after=current.get(self.merge_destinations.get(e, e)),
                **({"relation": "merged"} if e in self.merge_destinations else {}),
            )
            for p, m, _, e, _ in self.original_measures
        ]
        originals = {e for _, _, _, e, _ in self.original_measures}
        rows.extend(
            dict(before=None, after=location)
            for e, location in current.items()
            if e not in originals
        )
        return dict(operations=self.ledger, mapping=dict(measures=rows))
