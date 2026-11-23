"""Single-assignment, offline ACP worker for a reviewed print-width specification."""
import base64
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys


WEIGHT_SHA256 = "2af3b81862c6be03c769683af18efdadb2c33f60ff32ab6f83e42c043d6c7816"
MODEL_LABEL = "TinyLlama 1.1B"
NUMBER = r"[0-9]{1,6}(?:\.[0-9]{1,6})?"
CAD = r"[\w.-]+\.step"


def grounded_result(spec, answer):
    """Accept only one model-extracted triple supported by the supplied spec."""
    match = re.fullmatch(rf"\s*({CAD})\s*\|\s*({NUMBER})\s*\|\s*({NUMBER})\s*\|?\s*", answer, re.I)
    if not match:
        raise ValueError("The worker could not extract one CAD file, width and tolerance")
    file, width, tolerance = match.groups()
    files = re.findall(rf"(?<![\w.-])({CAD})(?![\w.-])", spec, re.I)
    dimensions = re.findall(rf"\bwidth\s+({NUMBER})\s*mm\s*(?:±|\+/-)\s*({NUMBER})\s*mm\b", spec, re.I)
    if (files != [file] or dimensions != [(width, tolerance)]
            or len(re.findall(r"\bwidth\b", spec, re.I)) != 1
            or len(re.findall(r"±|\+/-", spec)) != 1):
        raise ValueError("The extracted fields differ from the supplied specification or are ambiguous")
    width, tolerance = Decimal(width), Decimal(tolerance)
    if not 0 <= tolerance < width:
        raise ValueError("Check the width and tolerance")
    return f"{file}: {width-tolerance:f}–{width+tolerance:f} mm"


def review_report(job, answer):
    brief = job["brief"]
    try:
        result = grounded_result(brief["spec"], answer)
        status = "done"
    except ValueError:
        status = "pending"
        result = ("Clarification requested: confirm one CAD filename, nominal width in mm "
                  "and symmetric tolerance in mm.")
    return {
        "schema": "workroom-update/v1",
        "taskId": job["taskId"],
        "sendId": job["sendId"],
        "goal": brief["spec"],
        "checklist": [{"id": "fit", "text": "Calculate the tray width range", "status": status}],
        "result": result,
        "evidence": f'{brief["source"]} / {brief["revision"]} / {MODEL_LABEL} (CPU)',
    }


def extract(spec):
    # The model sees only the spec, never the full host conversation or identifiers.
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_PROGRESS_BARS="1", HOME="/tmp",
                      OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", TOKENIZERS_PARALLELISM="false")
    from transformers import AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
    import torch

    if torch.cuda.is_available():
        raise RuntimeError("This worker is qualified only for CPU inference")
    weights = Path("/model/weights.gguf")
    with weights.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != WEIGHT_SHA256:
            raise ValueError("Unrecognized worker weights")
    opts = dict(gguf_file=weights.name, local_files_only=True, trust_remote_code=False)
    tokenizer = AutoTokenizer.from_pretrained(weights.parent, **opts)
    model = AutoModelForCausalLM.from_pretrained(weights.parent, dtype=torch.float32, **opts).eval()
    messages = [
        {"role":"system", "content":"Extract the CAD filename, nominal width in mm, and tolerance in mm. "
         "Copy the three values exactly, on one line: filename | width | tolerance. Do not calculate."},
        {"role":"user", "content":"Plate width 72 mm ±0.1 mm. CAD plate-v1.step"},
        {"role":"assistant", "content":"plate-v1.step | 72 | 0.1"},
        {"role":"user", "content":spec},
    ]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt", return_dict=True)
    start = inputs["input_ids"].shape[1]

    class EndOfRow(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            row = tokenizer.decode(input_ids[0, start:], skip_special_tokens=True)
            return row.count("|") >= 3 or "\n" in row.strip(" \t")

    with torch.inference_mode():
        output = model.generate(**inputs, do_sample=False, max_new_tokens=48, pad_token_id=tokenizer.eos_token_id,
                                stopping_criteria=StoppingCriteriaList([EndOfRow()]))
    return tokenizer.decode(output[0, start:], skip_special_tokens=True)


def read_message():
    raw = sys.stdin.buffer.readline(131073)
    if not raw.endswith(b"\n") or len(raw) > 131072:
        raise ValueError("Incomplete or oversized ACP message")
    return json.loads(raw)


def send(**message):
    print(json.dumps({"jsonrpc":"2.0", **message}), flush=True)


def serve():
    init = read_message()
    if init.get("method") != "initialize" or init["params"]["protocolVersion"] != 1:
        raise ValueError("Expected ACP initialization")
    send(id=init["id"], result={"protocolVersion":1, "agentCapabilities":{}})
    new = read_message()
    if new.get("method") != "session/new" or new["params"]["mcpServers"]:
        raise ValueError("Expected one session without MCP servers")
    session = "print-spec"
    send(id=new["id"], result={"sessionId":session})
    prompt = read_message()
    if prompt.get("method") != "session/prompt" or prompt["params"]["sessionId"] != session:
        raise ValueError("Unexpected prompt")
    text = "\n".join(item["text"] for item in prompt["params"]["prompt"] if item["type"] == "text")
    tokens = set(re.findall(r"PRINT_INPUT\[([A-Za-z0-9+/=]+)\]", text))
    if len(tokens) != 1:
        raise ValueError("Expected one assignment")
    job = json.loads(base64.b64decode(tokens.pop(), validate=True))
    brief = job["brief"]
    if set(job) != {"brief","taskId","sendId"} or set(brief) != {"project","revision","source","spec"}:
        raise ValueError("Unexpected assignment fields")
    spec = brief["spec"]
    if not isinstance(spec, str) or not 1 <= len(spec) <= 1000:
        raise ValueError("Expected one bounded print specification")
    report = review_report(job, extract(spec))
    send(method="session/update", params={"sessionId":session,"update":{"sessionUpdate":"agent_message_chunk",
         "content":{"type":"text","text":json.dumps(report)}}})
    send(id=prompt["id"], result={"stopReason":"end_turn"})


if __name__ == "__main__":
    serve()
