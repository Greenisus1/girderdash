"""pi18n - shared translation loader for Greenisus1 Pi apps.

All app text is controlled by the Translations app, which writes:
  ~/pi-translations/language      current language code (e.g. "es"; absent = English)
  ~/pi-translations/<app>.json    {"lang": "es", "strings": {KEY: "..."}}

Apps call load(app, defaults) and use the returned dict. If the Translations
app is not installed, or no pack exists for the current language, the app's
built-in English defaults are used - every app still runs zero-setup.
Do not edit the generated JSON by app code; only the Translations app writes it.
"""
import json, os

DIR = os.environ.get("PI18N_DIR") or os.path.expanduser("~/pi-translations")

def current_language():
    try:
        with open(os.path.join(DIR, "language")) as fh:
            lang = fh.read().strip().lower()
            return lang or "en"
    except OSError:
        return "en"

def load(app, defaults):
    """Return {KEY: text} for the current language, falling back to defaults."""
    out = dict(defaults)
    lang = current_language()
    if lang == "en":
        return out
    try:
        with open(os.path.join(DIR, app + ".json")) as fh:
            data = json.load(fh)
        if data.get("lang") == lang:
            for k, v in data.get("strings", {}).items():
                if k in out and isinstance(v, str) and v:
                    out[k] = v
    except (OSError, ValueError):
        pass
    return out
