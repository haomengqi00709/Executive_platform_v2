IS_ACTION = True


def build(ctx):
    def run_outreach(context_note: str = "", folder: str = "",
                     tag: str = "", recent_hours: int = 0) -> str:
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            from src.modules.outreach import run as _run_outreach
            from src.ai import AIClient
            _ai = AIClient(settings=ctx.settings)
            result = _run_outreach(
                graph=owner_graph,
                ai=_ai,
                data_dir=ctx.data_dir,
                settings=ctx.settings,
                context_note=context_note,
                folder=folder,
                tag=tag,
                recent_hours=recent_hours,
            )
            if result.get("status") == "not_run":
                return f"❌ {result.get('error', 'Unknown error')}"
            s = result.get("summary", {})
            msg = (f"✅ Outreach run complete:\n"
                   f"  • {s.get('drafts', 0)} drafts saved to Outlook\n"
                   f"  • {s.get('skipped', 0)} contacts skipped (missing email or generation failed)")
            if s.get("files"):
                msg += f"\n  • {s['files']} files processed"
            if s.get("errors", 0):
                msg += f"\n  • {s['errors']} errors"
            return msg
        except Exception as e:
            return f"Error running outreach: {e}"
    return run_outreach
