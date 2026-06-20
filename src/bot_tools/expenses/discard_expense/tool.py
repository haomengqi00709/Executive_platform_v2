IS_ACTION = True


def build(ctx):
    def discard_expense() -> str:
        ctx.state["pending_expense"] = None
        return "Expense discarded."
    return discard_expense
