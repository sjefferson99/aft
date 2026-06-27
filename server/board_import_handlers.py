"""Board import handlers.

This module provides an extensible handler framework so new import formats
can be added without changing endpoint logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

_MAX_DESCRIPTION_LENGTH = 2000


def get_payload_list(payload, key):
    """Return a payload key as list, defaulting to empty list."""
    value = payload.get(key)
    return value if isinstance(value, list) else []


@dataclass
class ImportValidationResult:
    """Result of import payload validation."""

    is_valid: bool
    errors: list = field(default_factory=list)


class BoardImportHandler(ABC):
    """Base class for board import handlers."""

    @abstractmethod
    def validate(self, payload) -> ImportValidationResult:
        """Validate payload structure and return ImportValidationResult."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, payload, options=None) -> dict:
        """Parse payload into normalized import schema.

        Args:
            payload: The parsed JSON payload.
            options: Optional dict of handler-specific import options.
        """
        raise NotImplementedError


class AFTBoardImportHandler(BoardImportHandler):
    """Import handler for native AFT board export files."""

    FORMAT = "aft-board"
    SUPPORTED_MAJOR_VERSION = "1"

    REQUIRED_ROOT_KEYS = {
        "export",
        "board",
        "board_settings",
        "columns",
        "cards",
        "card_secondary_assignees",
        "checklists",
        "comments",
        "scheduled_cards",
    }

    def validate(self, payload) -> ImportValidationResult:
        errors = []

        if not isinstance(payload, dict):
            return ImportValidationResult(False, ["Import payload must be a JSON object"])

        missing_keys = sorted(self.REQUIRED_ROOT_KEYS - set(payload.keys()))
        if missing_keys:
            errors.append(f"Missing required top-level keys: {', '.join(missing_keys)}")

        export_meta = payload.get("export")
        if not isinstance(export_meta, dict):
            errors.append("Missing or invalid export metadata")
        else:
            format_name = export_meta.get("format")
            if format_name != self.FORMAT:
                errors.append("Unsupported export format. Expected aft-board")

            version = export_meta.get("format_version")
            if not isinstance(version, str) or not version:
                errors.append("Missing export.format_version")
            else:
                major = version.split(".", 1)[0]
                if major != self.SUPPORTED_MAJOR_VERSION:
                    errors.append(
                        f"Unsupported format major version {major}. "
                        f"Expected {self.SUPPORTED_MAJOR_VERSION}.x"
                    )

        board = payload.get("board")
        if not isinstance(board, dict):
            errors.append("board must be an object")
        else:
            board_name = board.get("name")
            if not isinstance(board_name, str) or not board_name.strip():
                errors.append("board.name is required and must be a non-empty string")
            if board.get("description") is not None and not isinstance(board.get("description"), str):
                errors.append("board.description must be a string or null")

        list_keys = [
            "board_settings",
            "columns",
            "cards",
            "card_secondary_assignees",
            "checklists",
            "comments",
            "scheduled_cards",
        ]
        for key in list_keys:
            value = payload.get(key)
            if not isinstance(value, list):
                errors.append(f"{key} must be an array")

        columns = get_payload_list(payload, "columns")
        cards = get_payload_list(payload, "cards")
        checklists = get_payload_list(payload, "checklists")
        comments = get_payload_list(payload, "comments")
        schedules = get_payload_list(payload, "scheduled_cards")

        column_ids = set()
        for index, column in enumerate(columns):
            if not isinstance(column, dict):
                errors.append(f"columns[{index}] must be an object")
                continue
            column_id = column.get("id")
            if not isinstance(column_id, int):
                errors.append(f"columns[{index}].id must be an integer")
            else:
                column_ids.add(column_id)
            column_name = column.get("name")
            if not isinstance(column_name, str) or not column_name.strip():
                errors.append(f"columns[{index}].name is required")

        card_ids = set()
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                errors.append(f"cards[{index}] must be an object")
                continue

            card_id = card.get("id")
            if not isinstance(card_id, int):
                errors.append(f"cards[{index}].id must be an integer")
            else:
                card_ids.add(card_id)

            column_id = card.get("column_id")
            if not isinstance(column_id, int) or column_id not in column_ids:
                errors.append(f"cards[{index}].column_id must reference a valid column")

            card_title = card.get("title")
            if not isinstance(card_title, str) or not card_title.strip():
                errors.append(f"cards[{index}].title is required")

        for index, item in enumerate(checklists):
            if not isinstance(item, dict):
                errors.append(f"checklists[{index}] must be an object")
                continue
            card_id = item.get("card_id")
            if not isinstance(card_id, int) or card_id not in card_ids:
                errors.append(f"checklists[{index}].card_id must reference a valid card")
            item_name = item.get("name")
            if not isinstance(item_name, str) or not item_name.strip():
                errors.append(f"checklists[{index}].name is required")

        for index, comment in enumerate(comments):
            if not isinstance(comment, dict):
                errors.append(f"comments[{index}] must be an object")
                continue
            card_id = comment.get("card_id")
            if not isinstance(card_id, int) or card_id not in card_ids:
                errors.append(f"comments[{index}].card_id must reference a valid card")
            comment_text = comment.get("comment")
            if not isinstance(comment_text, str) or not comment_text.strip():
                errors.append(f"comments[{index}].comment is required")

        schedule_ids = set()
        for index, schedule in enumerate(schedules):
            if not isinstance(schedule, dict):
                errors.append(f"scheduled_cards[{index}] must be an object")
                continue

            schedule_id = schedule.get("id")
            if isinstance(schedule_id, int):
                schedule_ids.add(schedule_id)

            template_card_id = schedule.get("card_id")
            if not isinstance(template_card_id, int) or template_card_id not in card_ids:
                errors.append(f"scheduled_cards[{index}].card_id must reference a valid card")

        for index, card in enumerate(cards):
            schedule_id = card.get("schedule")
            if schedule_id is None:
                continue
            if not isinstance(schedule_id, int) or schedule_id not in schedule_ids:
                errors.append(f"cards[{index}].schedule must reference a valid scheduled_cards entry")

        return ImportValidationResult(len(errors) == 0, errors)

    def parse(self, payload, options=None) -> dict:
        """Normalize payload with safe defaults for optional collections."""
        export_meta = payload.get("export") or {}

        return {
            "import_format": export_meta.get("format", self.FORMAT),
            "import_format_version": export_meta.get("format_version", "1.0"),
            "board": payload.get("board") or {},
            "board_settings": payload.get("board_settings") or [],
            "columns": payload.get("columns") or [],
            "cards": payload.get("cards") or [],
            "card_secondary_assignees": payload.get("card_secondary_assignees") or [],
            "checklists": payload.get("checklists") or [],
            "comments": payload.get("comments") or [],
            "scheduled_cards": payload.get("scheduled_cards") or [],
        }


class TrelloBoardImportHandler(BoardImportHandler):
    """Import handler for Trello board JSON export files."""

    FORMAT = "trello"

    def validate(self, payload) -> ImportValidationResult:
        errors = []

        if not isinstance(payload, dict):
            return ImportValidationResult(False, ["Import payload must be a JSON object"])

        board_name = payload.get("name")
        if not isinstance(board_name, str) or not board_name.strip():
            errors.append("Board name is required and must be a non-empty string")

        for key in ("lists", "cards", "checklists"):
            if not isinstance(payload.get(key), list):
                errors.append(f"{key} must be an array")

        if errors:
            return ImportValidationResult(False, errors)

        all_list_ids = {lst["id"] for lst in payload["lists"] if isinstance(lst, dict) and lst.get("id")}

        for index, lst in enumerate(payload["lists"]):
            if not isinstance(lst, dict):
                errors.append(f"lists[{index}] must be an object")
                continue
            if not lst.get("id"):
                errors.append(f"lists[{index}].id is required")
            list_name = lst.get("name")
            if not isinstance(list_name, str) or not list_name.strip():
                errors.append(f"lists[{index}].name is required")

        for index, card in enumerate(payload["cards"]):
            if not isinstance(card, dict):
                errors.append(f"cards[{index}] must be an object")
                continue
            if not card.get("id"):
                errors.append(f"cards[{index}].id is required")
            card_name = card.get("name")
            if not isinstance(card_name, str) or not card_name.strip():
                errors.append(f"cards[{index}].name is required")
            id_list = card.get("idList")
            if not id_list or id_list not in all_list_ids:
                errors.append(f"cards[{index}].idList must reference a valid list")

        return ImportValidationResult(len(errors) == 0, errors)

    def parse(self, payload, options=None) -> dict:
        """Convert a Trello board export to the normalised AFT import schema."""
        options = options or {}
        include_archived_cards = options.get("include_archived_cards", False)
        include_archived_lists = options.get("include_archived_lists", False)
        # member_map: {trello_member_id_str: aft_user_id_int}  (pre-validated by caller)
        member_map = options.get("member_map") or {}

        # --- Lists → columns ---
        all_lists = [lst for lst in payload.get("lists", []) if isinstance(lst, dict)]
        active_lists = [
            lst for lst in all_lists
            if include_archived_lists or not lst.get("closed", False)
        ]
        active_lists.sort(key=lambda l: (l.get("pos") or 0))

        list_id_map = {}  # Trello string id → sequential int
        columns = []
        for seq_id, lst in enumerate(active_lists, start=1):
            list_id_map[lst["id"]] = seq_id
            columns.append({
                "id": seq_id,
                "name": lst.get("name", ""),
                "order": seq_id - 1,
            })

        active_list_ids = set(list_id_map.keys())

        # --- Label lookup for description prefixes ---
        label_map = {}  # Trello label id → display name
        for lbl in payload.get("labels", []):
            if not isinstance(lbl, dict) or not lbl.get("id"):
                continue
            name = (lbl.get("name") or "").strip() or (lbl.get("color") or lbl.get("id", ""))
            label_map[lbl["id"]] = name

        # --- Checklist lookup: Trello checklist id → checklist object ---
        checklist_by_id = {}
        for cl in payload.get("checklists", []):
            if isinstance(cl, dict) and cl.get("id"):
                checklist_by_id[cl["id"]] = cl

        # --- Comment lookup: card id → list of (date, text) ---
        comments_by_card_id = {}
        for action in payload.get("actions", []):
            if not isinstance(action, dict) or action.get("type") != "commentCard":
                continue
            data = action.get("data") or {}
            card_obj = data.get("card")
            card_id = card_obj.get("id") if isinstance(card_obj, dict) else None
            text = data.get("text")
            if not card_id or not isinstance(text, str) or not text.strip():
                continue
            comments_by_card_id.setdefault(card_id, []).append({
                "date": action.get("date"),
                "text": text,
            })

        # --- Cards, checklists, comments ---
        all_cards = [c for c in payload.get("cards", []) if isinstance(c, dict)]
        active_cards = [
            c for c in all_cards
            if c.get("idList") in active_list_ids
            and (include_archived_cards or not c.get("closed", False))
        ]
        active_cards.sort(key=lambda c: (
            list_id_map.get(c.get("idList"), 0),
            c.get("pos") or 0,
        ))

        card_id_map = {}  # Trello string id → sequential int
        cards = []
        checklist_items = []
        comments = []
        card_secondary_assignees = []
        checklist_seq = 1
        comment_seq = 1

        for seq_id, card in enumerate(active_cards, start=1):
            trello_card_id = card["id"]
            card_id_map[trello_card_id] = seq_id
            column_seq_id = list_id_map[card["idList"]]

            # Build description: label prefixes first, then original desc, then URL attachments
            desc_parts = []

            label_ids = card.get("idLabels") or []
            if label_ids:
                label_tags = " ".join(
                    f"[{label_map[lid]}]" for lid in label_ids if lid in label_map
                )
                if label_tags:
                    desc_parts.append(label_tags)

            original_desc = (card.get("desc") or "").strip()
            if original_desc:
                desc_parts.append(original_desc)

            url_attachments = [
                a for a in (card.get("attachments") or [])
                if isinstance(a, dict) and not a.get("isUpload") and a.get("url")
            ]
            if url_attachments:
                urls_text = "\n".join(a["url"] for a in url_attachments)
                desc_parts.append(urls_text)

            description = "\n\n".join(desc_parts) if desc_parts else None
            if description and len(description) > _MAX_DESCRIPTION_LENGTH:
                description = description[:_MAX_DESCRIPTION_LENGTH]

            # Date mapping
            end_date = card.get("due") or None
            start_date = card.get("start") or None

            # Member → assignee mapping
            id_members = card.get("idMembers") or []
            mapped_user_ids = [
                member_map[m] for m in id_members if m in member_map
            ]
            assigned_to_id = mapped_user_ids[0] if mapped_user_ids else None
            for secondary_user_id in mapped_user_ids[1:]:
                card_secondary_assignees.append({
                    "card_id": seq_id,
                    "user_id": secondary_user_id,
                })

            cards.append({
                "id": seq_id,
                "column_id": column_seq_id,
                "title": card.get("name", ""),
                "description": description,
                "order": seq_id - 1,
                "archived": bool(card.get("closed", False)),
                "scheduled": False,
                "schedule": None,
                "done": bool(card.get("dueComplete", False)),
                "start_date": start_date,
                "end_date": end_date,
                "assigned_to_id": assigned_to_id,
            })

            # Checklists
            trello_checklist_ids = card.get("idChecklists") or []
            card_checklists = [
                checklist_by_id[cl_id]
                for cl_id in trello_checklist_ids
                if cl_id in checklist_by_id
            ]
            card_checklists.sort(key=lambda cl: cl.get("pos") or 0)

            use_prefix = len(card_checklists) > 1
            for cl in card_checklists:
                group_name = (cl.get("name") or "").strip()
                items = cl.get("checkItems") or []
                items_sorted = sorted(items, key=lambda i: i.get("pos") or 0)
                for item in items_sorted:
                    if not isinstance(item, dict):
                        continue
                    item_name = (item.get("name") or "").strip()
                    if not item_name:
                        continue
                    if use_prefix and group_name:
                        item_name = f"{group_name}: {item_name}"
                    checklist_items.append({
                        "id": checklist_seq,
                        "card_id": seq_id,
                        "name": item_name,
                        "checked": item.get("state") == "complete",
                        "order": checklist_seq - 1,
                    })
                    checklist_seq += 1

            # Comments from actions
            card_comments = comments_by_card_id.get(trello_card_id, [])
            card_comments.sort(key=lambda c: c.get("date") or "")
            for cmt in card_comments:
                text = cmt["text"].strip()
                if not text:
                    continue
                comments.append({
                    "id": comment_seq,
                    "card_id": seq_id,
                    "comment": text,
                    "order": comment_seq - 1,
                    "created_at": cmt.get("date"),
                })
                comment_seq += 1

        return {
            "import_format": self.FORMAT,
            "import_format_version": "1.0",
            "board": {
                "name": (payload.get("name") or "").strip(),
                "description": (payload.get("desc") or "").strip() or None,
                "archived": bool(payload.get("closed", False)),
            },
            "board_settings": [],
            "columns": columns,
            "cards": cards,
            "card_secondary_assignees": card_secondary_assignees,
            "checklists": checklist_items,
            "comments": comments,
            "scheduled_cards": [],
        }


class ImportHandlerFactory:
    """Factory for obtaining import handlers by payload metadata."""

    @staticmethod
    def get_handler(payload):
        if not isinstance(payload, dict):
            return None

        # Detect AFT native export by format marker
        export_meta = payload.get("export")
        if isinstance(export_meta, dict):
            if export_meta.get("format") == AFTBoardImportHandler.FORMAT:
                return AFTBoardImportHandler()
            return None

        # Detect Trello export by structural fingerprint
        if (
            isinstance(payload.get("lists"), list)
            and isinstance(payload.get("cards"), list)
            and isinstance(payload.get("name"), str)
        ):
            return TrelloBoardImportHandler()

        return None
