import unicodedata


def compose_full_name(first_name, middle_name, last_name):
    parts = (first_name, middle_name, last_name)
    return " ".join(part.strip() for part in parts if part and part.strip())


def normalize_name(value):
    """Lowercase, strip accents and collapse spaces, so 'Peña ' matches 'pena'."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.casefold().split())