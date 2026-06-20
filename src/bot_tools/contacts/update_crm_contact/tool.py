IS_ACTION = True


def build(ctx):
    def update_crm_contact(email: str, field: str, value: str) -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import update_contact
            contact = update_contact(data_dir, email, field, value)
            return f"✅ Updated {field} for {email}: {value}"
        except Exception as e:
            return f"Error updating CRM contact: {e}"
    return update_crm_contact
