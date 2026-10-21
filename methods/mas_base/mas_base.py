import os
import random
import threading
import openai
from tenacity import retry, wait_exponential, stop_after_attempt

from methods.utils import handle_retry_error, load_config
from utils.async_llm import create_llm_instance

# Retry count is configurable via AEGIS_LLM_RETRIES env var (default 5).
# When the API is flaky, set it higher (e.g. AEGIS_LLM_RETRIES=10) so
# transient failures don't propagate as silent None responses.
_LLM_RETRIES = int(os.environ.get("AEGIS_LLM_RETRIES", "5"))


# --------------------------------------------------------------------------- #
# Multimodal helpers
# --------------------------------------------------------------------------- #
def _image_to_openai_part(ref) -> dict:
    """Convert one image reference (path / URL / data URL) into an OpenAI
    'image_url' content part. Local paths are read and base64-encoded into a
    data URL so we don't depend on uploaded-file URLs.
    """
    import base64, mimetypes
    # If a dict was passed (already an image part), forward it.
    if isinstance(ref, dict) and ref.get("type") == "image_url":
        return ref
    s = str(ref)
    if s.startswith(("http://", "https://", "data:")):
        return {"type": "image_url", "image_url": {"url": s}}
    # Local path -> base64 data URL
    if not os.path.exists(s):
        raise FileNotFoundError(
            f"Image not found at {s}. "
            f"This usually means the dataset JSON has stale absolute paths from a "
            f"previous conversion. Re-run main.py with "
            f"--images_dir /absolute/path/to/medxpertqa_images to resolve "
            f"image filenames at runtime."
        )
    mime, _ = mimetypes.guess_type(s)
    if not mime or not mime.startswith("image/"):
        # Best-effort default; OpenAI accepts jpeg/png/gif/webp.
        mime = "image/jpeg"
    with open(s, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _audio_to_openai_part(ref, style="data_uri"):
    """One audio ref -> an OpenAI-compatible `input_audio` content part.

    `ref` is a local path, an http(s) URL, or a data URI. style:
      - "data_uri" (default; Xiaomi MiMo docs): input_audio.data = "data:audio/<fmt>;base64,..."
                   or the URL itself, plus input_audio.format
      - "openai"  : input_audio.data = raw base64, input_audio.format = "<fmt>"
    """
    import base64, mimetypes
    if isinstance(ref, str) and (ref.startswith("http://") or ref.startswith("https://") or ref.startswith("data:")):
        fmt = "wav"
        if ref.startswith("data:audio/"):
            fmt = ref[len("data:audio/"):].split(";", 1)[0] or "wav"
        return {"type": "input_audio", "input_audio": {"data": ref, "format": fmt}}
    path = os.path.abspath(ref)
    fmt = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    if style == "openai":
        return {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}}
    mime = mimetypes.types_map.get("." + fmt, f"audio/{fmt}")
    if fmt == "wav":
        mime = "audio/wav"
    return {"type": "input_audio", "input_audio": {"data": f"data:{mime};base64,{b64}", "format": fmt}}


def _attach_audios_to_messages(messages, audios, style="data_uri"):
    """Like _attach_images_to_messages but for audio: the LAST user message gets
    the audio parts placed BEFORE its text (Qwen-Audio / MAM order: audio, text)."""
    if not audios:
        return messages
    parts = [_audio_to_openai_part(a, style) for a in audios]
    new_msgs = [dict(m) for m in messages]
    idx = next((i for i in range(len(new_msgs) - 1, -1, -1) if new_msgs[i].get("role") == "user"), None)
    if idx is None:
        new_msgs.append({"role": "user", "content": parts})
        return new_msgs
    content = new_msgs[idx].get("content", "")
    text_parts = [{"type": "text", "text": content}] if isinstance(content, str) and content else (
        list(content) if isinstance(content, list) else [])
    new_msgs[idx]["content"] = parts + text_parts
    return new_msgs


def _attach_images_to_messages(messages, images):
    """Return a NEW messages list where the LAST user message carries the given
    images (in addition to its existing text). Other messages are untouched.

    If `messages` has no user message, one is appended carrying just the images.
    Strings in `messages[*].content` are upgraded to the OpenAI parts-list
    format. Already-parts-list contents are extended.
    """
    if not images:
        return messages
    parts_for_images = [_image_to_openai_part(r) for r in images]

    # Walk messages from the end to find the last user message.
    new_msgs = [dict(m) for m in messages]  # shallow copy
    target_idx = None
    for i in range(len(new_msgs) - 1, -1, -1):
        if new_msgs[i].get("role") == "user":
            target_idx = i
            break
    if target_idx is None:
        # No user message — append one carrying only the images.
        new_msgs.append({"role": "user", "content": parts_for_images})
        return new_msgs

    target = new_msgs[target_idx]
    content = target.get("content", "")
    if isinstance(content, str):
        new_content = [{"type": "text", "text": content}] if content else []
    elif isinstance(content, list):
        new_content = list(content)
    else:
        new_content = [{"type": "text", "text": str(content)}]
    new_content.extend(parts_for_images)
    target["content"] = new_content
    new_msgs[target_idx] = target
    return new_msgs


def _extract_call_meta(completion, model_name, request_dict) -> dict:
    """Per-call metadata from an OpenAI-compatible chat completion.

    `reasoning` is the provider's separate reasoning text when it returns one
    (`reasoning_content`: DeepSeek / Qwen / vLLM / SGLang; `reasoning`:
    OpenRouter); None when the model has no separate reasoning channel.
    """
    meta = {"model": model_name, "max_tokens": request_dict.get("max_tokens")}
    # The model the provider says actually served the call. Aggregators may
    # route a model name to another model (2026-10-21: aihubmix answered
    # "llama-4-maverick" requests with google/gemma-4-31B-it-turbo), so the
    # requested name alone does not identify the backbone.
    served = getattr(completion, "model", None)
    meta["served_model"] = served if isinstance(served, str) else None
    try:
        choice = completion.choices[0]
        msg = choice.message
        extra = getattr(msg, "model_extra", None) or {}
        reasoning = (getattr(msg, "reasoning_content", None) or extra.get("reasoning_content")
                     or getattr(msg, "reasoning", None) or extra.get("reasoning"))
        meta["reasoning"] = reasoning if isinstance(reasoning, str) and reasoning else None
        meta["finish_reason"] = getattr(choice, "finish_reason", None)
    except Exception:
        meta.setdefault("reasoning", None)
        meta.setdefault("finish_reason", None)
    usage = getattr(completion, "usage", None)
    meta["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
    meta["completion_tokens"] = getattr(usage, "completion_tokens", None)
    details = getattr(usage, "completion_tokens_details", None)
    meta["reasoning_tokens"] = getattr(details, "reasoning_tokens", None) if details is not None else None
    return meta


def _set_last_call_meta(inst, meta) -> None:
    tls = inst.__dict__.get("_call_meta_tls")
    if tls is None:
        tls = inst.__dict__["_call_meta_tls"] = threading.local()
    tls.meta = meta


def pop_last_call_meta(inst):
    """Return and clear the metadata of the latest call_llm on this thread."""
    tls = inst.__dict__.get("_call_meta_tls")
    if tls is None:
        return None
    meta = getattr(tls, "meta", None)
    tls.meta = None
    return meta


class MAS():

    def __init__(self, general_config, method_config_name=None):

        if method_config_name is not None:
            # Get the child class's module path
            child_module_path = os.path.dirname(os.path.abspath(self.__class__.__module__.replace('.', '/')))
            self.method_config = load_config(os.path.join(child_module_path, "configs", f"{method_config_name}.yaml"))
        
        self.model_api_config = general_config["model_api_config"]
        self.model_name = general_config["model_name"]
        self.model_temperature = general_config["model_temperature"]
        self.model_max_tokens = general_config["model_max_tokens"]
        self.model_timeout = general_config["model_timeout"]
        
        # Tracking compute costs
        self.token_stats = {
            self.model_name: {"num_llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        }

        self.memory_bank = {}
        self.tools = {}
        
    
    def inference(self, sample):
        """
        sample: data sample (dictionary) to be passed to the MAS
        """
        query = sample["query"]
        response = self.call_llm(prompt=query)
        return {"response": response}

    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(_LLM_RETRIES), retry_error_callback=handle_retry_error)
    def call_llm(self, prompt=None, system_prompt=None, messages=None,
                 model_name=None, temperature=None, images=None, audios=None, **kwargs):
        """Make a single LLM call.

        Args:
            prompt, system_prompt: text prompts; converted to messages if `messages` is None.
            messages: pre-built chat-completions message list. If provided and `images`
                is also given, images are attached to the LAST user message.
            images: optional list of image refs to attach to this call. Each ref may be:
                - a local filesystem path  (resolved + base64-encoded -> data URL)
                - an http(s):// URL        (passed through as-is)
                - a "data:image/..;base64,..." URL (passed through as-is)
              Images are sent in the OpenAI multimodal message format. Compatible
              with gpt-4o / gpt-4o-mini / gpt-5* / qwen3-vl-* etc. as long as the
              underlying provider speaks OpenAI's vision protocol.
        """
        model_name = model_name if model_name is not None else self.model_name
        model_dict = random.choice(self.model_api_config[model_name]["model_list"])
        model_name, model_url, api_key, provider = model_dict.get('model_name'), model_dict.get('model_url'), model_dict.get('api_key'), model_dict.get('provider')
        # `reasoning_effort` is a Gemini-2.5-flash-only knob. Two important caveats:
        #   1) the `-lite` family (e.g. gemini-2.5-flash-lite) has NO thinking
        #      mode and rejects this parameter, so we must NOT auto-add it.
        #   2) the parameter is opt-in: we only attach it when the user has
        #      explicitly set "reasoning_effort" in their model config. The
        #      previous default of "none" is not a valid OpenAI value and
        #      caused 400 Bad Request on some proxies.
        reasoning_effort = None
        if "gemini-2.5-flash" in model_name and "lite" not in model_name.lower():
            if "reasoning_effort" in model_dict:
                reasoning_effort = model_dict["reasoning_effort"]

        if messages is None:
            assert prompt is not None, "'prompt' must be provided if 'messages' is not provided."
            if system_prompt is not None:
                messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            else:
                messages = [{"role": "user", "content": prompt}]

        # ---- Multimodal: attach images to the last user message ----------- #
        if images:
            messages = _attach_images_to_messages(messages, images)
        # ---- Audio: attach input_audio parts to the last user message ---- #
        if audios:
            messages = _attach_audios_to_messages(
                messages, audios, style=model_dict.get("audio_input_style", "data_uri"))
        # ------------------------------------------------------------------- #

        model_temperature = temperature if temperature is not None else self.model_temperature

        request_dict = {
            "model": model_name,
            "messages": messages,
            # Per-call override (e.g. a framework's original per-stage budget);
            # falls back to the global model_max_tokens.
            "max_tokens": kwargs.get("max_tokens") or self.model_max_tokens,
            "timeout": self.model_timeout
        }
        if "o1" not in model_name:              # OpenAI's o1 models do not support temperature
            request_dict["temperature"] = model_temperature
        if reasoning_effort is not None:
            request_dict["reasoning_effort"] = reasoning_effort
        # Provider-specific request fields from model_api_config, e.g. MiMo's
        # {"thinking": {"type": "disabled"}} or Qwen's {"enable_thinking": false}.
        if model_dict.get("extra_body"):
            request_dict["extra_body"] = model_dict["extra_body"]

        # 根据是否有 base_url 来决定初始化方式
        if model_url and model_url.strip():
            llm = openai.OpenAI(base_url=model_url, api_key=api_key)
        else:
            # 对于 Azure OpenAI 或其他不需要 base_url 的情况
            if provider and provider == "azure":
                llm = openai.AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=model_dict.get("azure_endpoint"),
                    api_version=model_dict.get("api_version", "2025-03-01-preview")
                )
            else:
                # 默认 OpenAI 客户端
                llm = openai.OpenAI(api_key=api_key)
        
        try:
            completion = llm.chat.completions.create(**request_dict)
            response, num_prompt_tokens, num_completion_tokens = completion.choices[0].message.content, completion.usage.prompt_tokens, completion.usage.completion_tokens
            # Per-call metadata (reasoning text, finish_reason, token usage),
            # read by the FM wrappers right after this call returns and stored
            # on the matching step as `llm_meta`. Thread-local so a method
            # that parallelizes its own calls cannot mix up two calls' meta.
            _set_last_call_meta(self, _extract_call_meta(completion, model_name, request_dict))
        except Exception as e:
            # Wrap with diagnostic context so handle_retry_error can show the
            # user exactly which request failed (model, has_images, msg count,
            # approx payload size). The original exception is preserved via
            # `raise ... from e` so the traceback still leads back to the
            # underlying OpenAI / urllib / proxy error.
            has_images = any(
                isinstance(m.get("content"), list)
                and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
                for m in request_dict.get("messages", [])
            )
            try:
                import json as _json
                payload_size = len(_json.dumps(request_dict, ensure_ascii=False))
            except Exception:
                payload_size = -1
            ctx = (f"model={model_name} provider={provider} "
                   f"msgs={len(request_dict.get('messages', []))} "
                   f"has_images={has_images} payload_bytes~={payload_size}")
            raise RuntimeError(f"chat.completions.create failed [{ctx}]: {type(e).__name__}: {e}") from e
        finally:
            llm.close()     # TODO: Check if this is necessary

        if isinstance(response, str):       # in cases where response is None or an error message
            # (fixed 2026-10-20: the first call of a model name used to be
            # registered but not counted)
            stats = self.token_stats.setdefault(
                model_name, {"num_llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            stats["num_llm_calls"] += 1
            stats["prompt_tokens"] += num_prompt_tokens or 0
            stats["completion_tokens"] += num_completion_tokens or 0
        else:
            # Response was None -- most commonly because the provider's safety
            # filter blocked the content (Gemini does this on medical images
            # sometimes), or the proxy returned a malformed response. Include
            # diagnostic context so the user can tell apart "safety block"
            # from "rate limit" from "payload too big".
            has_images = any(
                isinstance(m.get("content"), list)
                and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
                for m in request_dict.get("messages", [])
            )
            finish_reason = None
            try:
                finish_reason = completion.choices[0].finish_reason
            except Exception:
                pass
            raise ValueError(
                f"Invalid (None) response from LLM. model={model_name} "
                f"has_images={has_images} finish_reason={finish_reason!r} "
                f"raw_response={response!r}. This often means the provider's "
                f"safety filter blocked the content, or the proxy returned an "
                f"empty completion."
            )
        
        return response
    def get_token_stats(self):
        return self.token_stats
    
    def optimizing(self, val_data):
        """
        For methods that requires validation data such as GPTSwarm and ADAS
        """
        pass

    def retrieve_memory(self):
        pass

    def update_memory(self):
        pass
    
    def get_tool(self):
        pass