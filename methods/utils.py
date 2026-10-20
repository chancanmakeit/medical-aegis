import yaml
import os
import traceback

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)
    return config


def handle_retry_error(retry_state):
    """Called by tenacity when all retries have been exhausted.

    Critical: print the actual underlying exception so users can diagnose WHY
    the API failed. The previous version just printed "Retry failed" and
    swallowed the real error, leaving downstream code to receive None with
    no context about whether it was a rate limit, safety block, payload size
    issue, parameter rejection, etc.

    Set AEGIS_RETRY_VERBOSE=full to also dump a full traceback (otherwise
    only the exception class + message is shown to keep logs readable).
    """
    attempt = retry_state.attempt_number
    exc = None
    try:
        if retry_state.outcome is not None:
            exc = retry_state.outcome.exception()
    except Exception:
        exc = None

    if exc is None:
        print(f"[Retry failed] all {attempt} attempts exhausted (no exception object available)")
        return None

    exc_name = type(exc).__name__
    exc_msg = str(exc)[:600]  # cap to avoid huge dumps
    print(f"[Retry failed] all {attempt} attempts exhausted. Last error: {exc_name}: {exc_msg}")

    if os.environ.get("AEGIS_RETRY_VERBOSE", "").lower() == "full":
        # Dump the full traceback for deep debugging.
        try:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            print(f"[Retry failed - full traceback]\n{tb}")
        except Exception:
            pass
    return None