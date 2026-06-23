import json

IS_ACTION = False


def build(ctx):
    # section_id → (registry list type, canonical id field) for cross-turn addressing.
    _SEC_MAP = {
        "reply_needed":         ("emails", "email_id"),
        "followup_needed":      ("emails", "email_id"),
        "commitments_extract":  ("commitments", "id"),
        "upcoming_commitments": ("commitments", "id"),
        "due_today":            ("commitments", "id"),
    }
    # Sections whose list the bot must show in FULL (deterministic render, identical to the
    # Teams briefing) rather than a model-typed subset — see _enforce_list_completeness in bot.py.
    _RENDER_SECTIONS = {
        "reply_needed", "followup_needed", "commitments_extract",
        "upcoming_commitments", "due_today",
    }

    def read_module_result(section_id: str) -> str:
        from src.bot import SECTION_IDS, _with_indices, _register_list
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        try:
            # Commitment lists come from the LIVE store (no snapshot-vs-state drift). The other
            # commitment view, upcoming_commitments, keeps reading its JSON projection because it
            # merges in meeting action items (the store's write_projection keeps it fresh/pruned).
            if section_id in ("commitments_extract", "due_today"):
                from src.modules import commitments_store as store
                from src.modules.tz import today_local_str
                today = today_local_str(ctx.data_dir)
                if section_id == "commitments_extract":
                    items = store.query_visible(ctx.data_dir, today)
                    data = {"id": section_id, "status": "fresh", "items": items}
                else:
                    items = store.query_due_today(ctx.data_dir, today)
                    data = {"id": section_id, "status": "fresh", "date": today, "items": items}
                data["count"] = len(items)
                data["empty"] = not items
            else:
                result_path = ctx.data_dir / "results" / f"{section_id}.json"
                if not result_path.exists():
                    return f"No results for '{section_id}' yet. Run the section first with run_skill()."
                data = json.loads(result_path.read_text())
                # Read-time handled overlay: an email the user already acted on (recorded live in
                # the store) drops off IMMEDIATELY here — no re-run of the slow/costly Graph+AI
                # section. The list stays the cached snapshot; only the cheap status is live.
                #   reply_needed    → drafted/replied, keyed on the inbound SENDER (from_email)
                #   followup_needed → dismissed,       keyed on the RECIPIENT  (to_email)
                if section_id in ("reply_needed", "followup_needed") and isinstance(data.get("items"), list):
                    try:
                        from src.modules import email_store
                        if section_id == "reply_needed":
                            kept, moved = email_store.overlay_handled(
                                ctx.data_dir, data["items"],
                                kinds=email_store.REPLY_KINDS, key_field="from_email")
                        else:
                            kept, moved = email_store.overlay_handled(
                                ctx.data_dir, data["items"],
                                kinds=email_store.FOLLOWUP_KINDS, key_field="to_email")
                        if moved:
                            # Append to the handled sidecar in the section's shape so
                            # check_email_handling recognizes an overlay-excluded item.
                            sidecar = data.get("handled") or []
                            for it in moved:
                                sidecar.append({
                                    "email_id":      it.get("email_id", ""),
                                    "email_subject": it.get("subject", ""),
                                    "email_from":    (it.get("from_email") or it.get("to_email") or "").lower(),
                                    "handled_by":    {"kind": it.get("_handled_kind", "")},
                                })
                            data["items"] = kept
                            data["handled"] = sidecar
                            data["count"] = len(kept)
                            data["empty"] = not kept
                    except Exception:
                        pass
            if isinstance(data.get("items"), list):
                _full_items = list(data["items"])   # uncapped, for a faithful canonical render
                # Order items to match exactly what the Teams briefing displays, so a "#N" the
                # user saw in a pushed briefing resolves to the same item here.
                try:
                    from src.server import _section_display_order
                    from zoneinfo import ZoneInfo
                    tzname = (ctx.settings or {}).get("timezone") or "UTC"
                    try:
                        tz = ZoneInfo(tzname)
                    except Exception:
                        tz = ZoneInfo("UTC")
                    ordered = _section_display_order(section_id, data, tz)
                except Exception:
                    ordered = data["items"]
                data["items"] = _with_indices(ordered)
                if section_id in _SEC_MAP:
                    _typ, _idf = _SEC_MAP[section_id]
                    _register_list(ctx, _typ, ordered, _idf,
                                   label_fn=lambda it: (it.get("description") or it.get("subject") or "")[:60],
                                   source=section_id)
                if section_id in _RENDER_SECTIONS:
                    # Approach 1: stash the deterministic full render (same renderer the Teams
                    # briefing uses) so the bot shows the COMPLETE list, never a model-truncated
                    # subset. bot.py's _enforce_list_completeness substitutes this if the model
                    # drops items. labels/count come from the SHOWN (capped) `ordered` list.
                    try:
                        from src.server import _format_section_for_teams
                        from zoneinfo import ZoneInfo
                        _tzname = (ctx.settings or {}).get("timezone") or "UTC"
                        try:
                            _tz = ZoneInfo(_tzname)
                        except Exception:
                            _tz = ZoneInfo("UTC")

                        def _lbl(it):
                            s = (it.get("description") or it.get("action")
                                 or it.get("subject") or it.get("title") or "")
                            return " ".join(s.split())[:40].lower()

                        _labels = [s for s in (_lbl(it) for it in ordered) if len(s) >= 8]
                        if isinstance(getattr(ctx, "state", None), dict):
                            ctx.state["_pending_render"] = {
                                "section_id": section_id,
                                "block": _format_section_for_teams({**data, "items": _full_items}, _tz),
                                "labels": _labels,
                                "count": len(_labels),
                            }
                    except Exception:
                        pass
            if isinstance(data.get("handled"), list):
                data["handled"] = _with_indices(data["handled"])
            print(f"[Bot] read_module_result({section_id})")
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading {section_id}: {e}"
    return read_module_result
