# NOTE:
# OpenROAD-flow-scripts must be installed and docker must be working.
# Ensure 'docker' command works in your terminal.
# REQUIREMENT:
# Codex CLI must be installed and accessible via command:
#   codex exec "prompt"
# Make sure you are logged in and API is working.
# Ensure iverilog and vvp are installed:
#   sudo apt install iverilog
import ast
import re
import subprocess
from pathlib import Path
import shutil
import os
import yaml
import sys
import random

# Paths
# USER CONFIGURATION:                        
PROJECT_ROOT = Path("/mnt/d/tempo/pytrial/vlsi_agent_project") # Change this path to your project directory
PROBLEMS_DIR = PROJECT_ROOT / "problems"
GEN_DIR = PROJECT_ROOT / "generated"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
LOGS_DIR = PROJECT_ROOT / "logs"

#  USER CONFIGURATION:
OPENROAD_FLOW_ROOT = Path.home() / "OpenROAD-flow-scripts" / "flow" # Path to OpenROAD-flow-scripts/flow directory
OPENROAD_PLATFORM = "sky130hd"   # change if using different PDK
OPENROAD_CLOCK_PERIOD = 1.1       # change if using different PDK
OPENROAD_CORE_UTILIZATION = 8     # percentage (small for toy designs)
OPENROAD_PLACE_DENSITY = 0.25     # placement density

GEN_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

MAX_ITERS = 6
DEFAULT_GENERIC_CYCLES = 256

KNOWN_MODULES = {
    "seq_detector_0011",
    "dot_product",
    "exp_fixed_point",
    "fp16_multiplier",
    "fir_filter",
}
#  USER CONFIGURATION:
VISIBLE_TB_DIR = PROJECT_ROOT / "visible_tb"  # Folder containing official visible testbenches (put visible testbenches here)

#  USER CONFIGURATION:
# Mapping of problem names to official testbench files
VISIBLE_TB_MAP = {
    "p1": "iclad_seq_detector_tb.v",
    "p5": "iclad_dot_product_tb.v",
    "p7": "iclad_exp_tb.v",
    "p8": "iclad_fp16_mult_tb.v",
    "p9": "iclad_fir_tb.v"
}
# Basic helpers
def save_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def sanitize_yaml_text(raw_text):
    out_lines = []
    for line in raw_text.splitlines():
        m = re.match(r"^(\s*[^:#][^:]*:\s*)(.+)$", line)
        if not m:
            out_lines.append(line)
            continue

        prefix = m.group(1)
        value = m.group(2).strip()

        if value.startswith(("'", '"', "|", ">")):
            out_lines.append(line)
            continue

        if value.startswith("[") and ("*" in value or "+" in value):
            safe_value = value.replace('"', '\\"')
            out_lines.append(f'{prefix}"{safe_value}"')
            continue

        out_lines.append(line)

    return "\n".join(out_lines) + "\n"

def read_yaml_safe(yaml_file):
    raw = Path(yaml_file).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        sanitized = sanitize_yaml_text(raw)
        data = yaml.safe_load(sanitized)

    if not isinstance(data, dict) or not data:
        raise ValueError("YAML file did not parse into a non-empty dictionary.")

    module_name = list(data.keys())[0]
    module_data = data[module_name]

    if not isinstance(module_data, dict):
        raise ValueError("Top-level YAML entry must map to a dictionary.")

    return module_name, module_data

def uses_systemverilog(signature_text):
    sv_tokens = [
        "logic",
        "parameter int",
        "][",
        "signed [",
        "output logic",
        "input  logic",
        "input logic",
        "always_ff",
        "always_comb",
    ]
    return any(tok in signature_text for tok in sv_tokens)

def extract_single_module(text, preferred_name=None):
    text = text.strip()

    # Remove markdown
    text = re.sub(r"^```[a-zA-Z0-9]*\n", "", text)
    text = re.sub(r"\n```$", "", text)

    # Try strict extraction
    m = re.search(r"(module\s+.*?endmodule)", text, re.DOTALL)

    if m:
        return m.group(1).strip() + "\n"

    # fallback extraction
    lines = text.splitlines()
    start = None
    end = None

    for i, line in enumerate(lines):
        if "module " in line and start is None:
            start = i
        if "endmodule" in line:
            end = i

    if start is not None and end is not None and end > start:
        return "\n".join(lines[start:end+1]) + "\n"

    raise RuntimeError("No valid module found in Codex output.")

def extract_numeric(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = re.search(r"-?\d+", value)
        if m:
            return int(m.group(0))
    raise ValueError(f"Could not extract numeric value from: {value!r}")

def peel_singletons(value):
    while isinstance(value, list) and len(value) == 1:
        value = value[0]
    return value


def normalize_list(value):
    value = peel_singletons(value)
    if isinstance(value, tuple):
        return list(value)
    return value

def summarize_ports(module_data):
    ports = module_data.get("ports", [])
    lines = []
    for p in ports:
        name = p.get("name", "")
        direction = p.get("direction", "")
        width = p.get("width", "")
        signed = p.get("signed", False)
        if width:
            lines.append(f"- {name} ({direction}) {'signed ' if signed else ''}{width}")
        else:
            lines.append(f"- {name} ({direction})")
    return "\n".join(lines) if lines else "(none)"

def summarize_parameters(module_data):
    params = module_data.get("parameters", {})
    if not params:
        return "(none)"
    return "\n".join([f"- {k} = {v}" for k, v in params.items()])

def summarize_sample_data(module_data):
    lines = []

    if "sample_input" in module_data:
        lines.append("sample_input:")
        lines.append(str(module_data["sample_input"]))

    if "sample_output" in module_data:
        lines.append("sample_output:")
        lines.append(str(module_data["sample_output"]))

    if "sample_usage" in module_data:
        lines.append("sample_usage:")
        try:
            lines.append(yaml.safe_dump(module_data["sample_usage"], sort_keys=False).strip())
        except Exception:
            lines.append(str(module_data["sample_usage"]))

    if "stimulus" in module_data:
        lines.append("stimulus:")
        try:
            lines.append(yaml.safe_dump(module_data["stimulus"], sort_keys=False).strip())
        except Exception:
            lines.append(str(module_data["stimulus"]))

    if "expected_y_out" in module_data:
        lines.append("expected_y_out:")
        lines.append(str(module_data["expected_y_out"]))

    return "\n".join(lines).strip() if lines else "(none)"

def infer_compile_target(stderr_text):
    s = stderr_text.lower()

    if re.search(r"tb\.sv:\d+", s):
        return "tb"
    if re.search(r"design\.sv:\d+", s):
        return "rtl"

    if "testbench" in s or "module tb" in s:
        return "tb"
    if "port" in s and ("connection" in s or "instantiation" in s or "mismatch" in s):
        return "tb"
    if "undeclared" in s or "syntax error" in s or "invalid module item" in s:
        return "rtl"

    return "unknown"

def classify_compile_error(stderr_text):
    s = stderr_text.lower()

    if "syntax error" in s:
        return "syntax_error"
    if "undeclared" in s or "not declared" in s:
        return "undeclared_signal"
    if "port" in s and ("mismatch" in s or "does not" in s or "wrong number" in s):
        return "port_mismatch"
    if "dimension" in s or "range" in s or "packed" in s or "unpacked" in s:
        return "array_or_width_issue"
    if "invalid module item" in s:
        return "rtl_structure_error"
    if "parameter" in s:
        return "parameter_issue"
    if "cannot assign" in s or "lvalue" in s:
        return "assignment_issue"
    if "break statements not supported" in s:
        return "unsupported_break"
    if "error" in s:
        return "unknown_compile_error"
    return "unknown_compile_error"

def parse_port_decls_from_signature(signature):
    if "(" not in signature or ")" not in signature:
        return []

    body = signature[signature.find("(") + 1: signature.rfind(")")].strip()
    if not body:
        return []

    parts = [p.strip() for p in body.split(",") if p.strip()]
    ports = []
    last_dir = None
    last_prefix = None

    for part in parts:
        if part.startswith("parameter ") or part.startswith("#("):
            continue

        m = re.match(r"^(input|output|inout)\s+(.*)$", part, flags=re.IGNORECASE)
        if m:
            direction = m.group(1).lower()
            rest = m.group(2).strip()

            name_m = re.match(r"^(.*?)([A-Za-z_][A-Za-z0-9_]*)$", rest)
            if not name_m:
                continue

            prefix = name_m.group(1).strip()
            name = name_m.group(2).strip()

            width = "".join(re.findall(r"(\[[^\]]+\])", prefix))
            signed = "signed" in prefix.lower()

            ports.append({
                "name": name,
                "direction": direction,
                "width": width,
                "signed": signed,
            })
            last_dir = direction
            last_prefix = prefix
            continue

        if last_dir and last_prefix is not None:
            name_m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", part)
            if not name_m:
                continue

            name = name_m.group(1)
            width = "".join(re.findall(r"(\[[^\]]+\])", last_prefix))
            signed = "signed" in last_prefix.lower()

            ports.append({
                "name": name,
                "direction": last_dir,
                "width": width,
                "signed": signed,
            })

    return ports

def safe_eval_ast(node):
    if isinstance(node, ast.Expression):
        return safe_eval_ast(node.body)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [safe_eval_ast(e) for e in node.elts]

    if isinstance(node, ast.Tuple):
        return [safe_eval_ast(e) for e in node.elts]

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        val = safe_eval_ast(node.operand)
        if isinstance(val, (int, float)):
            return -val
        raise ValueError("Unsupported unary operand.")

    if isinstance(node, ast.BinOp):
        left = safe_eval_ast(node.left)
        right = safe_eval_ast(node.right)

        if isinstance(node.op, ast.Add):
            return left + right

        if isinstance(node.op, ast.Mult):
            if isinstance(left, list) and isinstance(right, int):
                return left * right
            if isinstance(right, list) and isinstance(left, int):
                return right * left
            if isinstance(left, str) and isinstance(right, int):
                return left * right
            if isinstance(right, str) and isinstance(left, int):
                return right * left
            return left * right

    raise ValueError("Unsupported expression.")

def safe_parse_sequence(expr):
    if expr is None:
        return None

    if isinstance(expr, list):
        return expr

    if isinstance(expr, tuple):
        return list(expr)

    if isinstance(expr, int):
        return [expr]

    if not isinstance(expr, str):
        return None

    s = expr.split("#", 1)[0].strip()
    if not s:
        return None

    if re.fullmatch(r"\d+'[bBhHdDoOxX][0-9a-fA-F_xXzZ]+", s):
        return [s]

    if re.fullmatch(r"-?\d+", s):
        return [int(s)]

    try:
        tree = ast.parse(s, mode="eval")
        val = safe_eval_ast(tree)
        if isinstance(val, list):
            return val
        return [val]
    except Exception:
        return None

def format_sv_value(value):
    if value is None:
        return "'0"
    if isinstance(value, bool):
        return f"1'b{int(value)}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        raw = value.split("#", 1)[0].strip()
        return raw if raw else "'0"
    return str(value)

def find_sequence_for_port(port_name, module_data):
    sources = []
    if isinstance(module_data.get("sample_usage"), dict):
        sources.append(module_data["sample_usage"])
    if isinstance(module_data.get("stimulus"), dict):
        sources.append(module_data["stimulus"])
    sources.append(module_data)

    candidate_keys = [
        port_name,
        f"{port_name}_sequence",
        f"{port_name}_values",
        f"{port_name}_stimulus",
    ]
    ignore_keys = {"period_cycles", "expected_high_cycles", "expected_low_cycles"}
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in candidate_keys:
            if key in ignore_keys:
                        continue
            if key in src:
                val = src[key]

                # If it's a scalar (like "8'd128") then treat as constant
                if isinstance(val, str) and re.fullmatch(r"\d+'[bdhBDH][0-9a-fA-F_xXzZ]+", val.strip()):
                    return [val] * DEFAULT_GENERIC_CYCLES

                # fallback
                seq = safe_parse_sequence(val)
                if seq is not None:
                    return normalize_list(seq)

    if port_name == "data_in" and "sample_input" in module_data:
        raw = module_data["sample_input"]
        if isinstance(raw, str):
            bit_string = raw.strip().split("#", 1)[0].strip()
            if re.fullmatch(r"[01_]+", bit_string):
                return list(bit_string.replace("_", ""))
        seq = safe_parse_sequence(raw)
        if seq is not None:
            return normalize_list(seq)

    return None

def find_expected_values_for_output(module_data, output_name):
    sources = []
    if isinstance(module_data.get("sample_usage"), dict):
        sources.append(module_data["sample_usage"])
    if isinstance(module_data.get("stimulus"), dict):
        sources.append(module_data["stimulus"])
    sources.append(module_data)

    candidate_keys = [
        f"expected_{output_name}",
        f"{output_name}_expected",
        output_name,
    ]

    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in candidate_keys:
            if key in src:
                seq = safe_parse_sequence(src[key])
                if seq is not None:
                    return normalize_list(seq)

    return None

# Prompt builders for RTL
def common_rtl_rules(signature):
    prompt_lang = "SystemVerilog" if uses_systemverilog(signature) else "Verilog"
    rules = f"""
IMPORTANT:
- Follow this exact module signature exactly:
{signature}

SYNTHESIS RULES (VERY IMPORTANT):
- Use ONLY synthesizable RTL (target: Yosys + OpenROAD).
- Use synchronous reset ONLY:
  - Use: always @(posedge clk)
  - Do NOT use: posedge reset or negedge reset
- Reset must be handled inside the clocked always block:
  if (reset) ...
- Avoid asynchronous reset completely.
- Ensure deterministic behavior across runs
- Avoid random or undefined initial values
- Use non-blocking assignments (<=) inside sequential always blocks.
- Use blocking assignments (=) only in combinational always @(*) blocks.

- Always provide default assignments in combinational blocks:
  → to avoid latch inference.

- Do NOT infer latches under any condition.

- Avoid:
  - incomplete if/else
  - missing default in case
  - partial assignments

- Keep FSMs simple and fully specified.

- Avoid complex expressions in one line:
  → use intermediate signals

- Keep arithmetic widths explicit and safe.

- Avoid:
  - break / continue
  - dynamic indexing in constant expressions
  - unsupported constructs

- Ensure outputs are stable and registered if sequential.

GENERAL RULES:
- Use the same language style as the signature.
- Do not rename module or ports.
- Do not add extra ports.
- Do not include testbench code.
- Output COMPLETE module from 'module' to 'endmodule'.

CRITICAL:
- Output ONLY RTL code.
- NO explanation.
- MUST start with 'module' and end with 'endmodule'.
""".strip()
    rules += """

CRITICAL:
- Do NOT explain anything.
- Do NOT describe changes.
- Do NOT reference files.
- Output ONLY RTL code.
- The output MUST start with 'module' and end with 'endmodule'.
"""
    return rules, prompt_lang

def build_rtl_prompt(module_name, module_data):
    signature = module_data["module_signature"]
    rules, lang = common_rtl_rules(signature)

    desc = module_data.get("description", "")
    seq = module_data.get("sequence_to_detect", "")
    tech = module_data.get("tech_node", "")
    clk = module_data.get("clock_period", "")

    prompt = f"""
You are a hardware design expert.

Generate synthesizable {lang} RTL for the following specification.

Module Name: {module_name}
Description: {desc}
""".strip() + "\n"

    if module_name == "exp_fixed_point":
        prompt += """
Additional rules for this module:
- Keep the design pipelined and synthesizable.
- Avoid constant part-selects inside always blocks.
- Avoid indefinite-width concatenations.
- Use explicit intermediate registers for x^2 and x^3.
- Keep all arithmetic widths explicit.
- Do not try to compress the whole Taylor series into one expression.
- The output is pipelined and may appear after a few cycles of latency.
""".strip() + "\n"

    if module_name == "seq_detector_0011":
        prompt += """
    Additional rules:
    - Implement FSM using synchronous reset.
    - Output 'detected' must be registered.
    - Avoid Mealy glitches; keep output stable.
    """.strip() + "\n"
        
    if module_name == "dot_product":
        prompt += """
    Additional rules for this module:

    - DO NOT use variable indexing like A[i] or B[i] inside expressions.
    - DO NOT use loops inside combinational logic.

    - Instead, manually unroll the dot product:
    dot_out = A[0]*B[0] + A[1]*B[1] + ... + A[N-1]*B[N-1];

    - Use explicit signed multiplication and addition.
    - Use intermediate wires if needed.

    - Keep everything fully synthesizable and simple.
    """.strip() + "\n"
    if module_name == "fp16_multiplier":
        prompt += """
    Additional rules for this module (VERY IMPORTANT):

    - Implement IEEE-like FP16 multiply (sign, exponent, mantissa).
    - DO NOT use undefined intermediate signals.
    - DO NOT leave any signals unassigned.

    - Always initialize ALL temporary signals.
    - Avoid partial assignments in always blocks.

    - Use ONLY:
    - assign statements OR
    - fully specified always @(*) blocks

    - If using always @(*):
    → assign default values at top of block

    - DO NOT infer latches under any condition.

    - Keep logic simple:
    - extract sign, exponent, mantissa
    - multiply mantissas
    - normalize result
    - adjust exponent

    - All outputs must be deterministic (no 'x').

    - Avoid deeply nested expressions.

    CRITICAL:
    - Output must be fully synthesizable
    - No syntax errors
    """
    if tech:
        prompt += f"\nTechnology Node: {tech}\n"
    if clk:
        prompt += f"Clock Period: {clk}\n"
    if seq:
        prompt += f"Sequence to detect: {seq}\n"

    if module_data.get("parameters"):
        prompt += "\nParameters:\n"
        prompt += summarize_parameters(module_data) + "\n"

    if module_data.get("ports"):
        prompt += "\nPorts:\n"
        prompt += summarize_ports(module_data) + "\n"

    prompt += "\n" + rules + "\n"
    return prompt.strip() + "\n"

def build_rtl_feedback_prompt(module_name, module_data, expected_text, actual_text):
    signature = module_data["module_signature"]
    rules, lang = common_rtl_rules(signature)

    return f"""
The generated {lang} code compiled and ran, but failed verification.

Module Name: {module_name}
Description: {module_data.get("description", "")}

Expected:
{expected_text}

Actual:
{actual_text}

Please correct the RTL so that verification passes.

{rules}

Additional guidance:
- Fix synthesis issues related to reset style and latch inference.
- Ensure synchronous reset and fully specified combinational logic.
- Preserve the exact behavior required by the specification.
- If the bug is timing/latency related, adjust output timing carefully.
- If the bug is arithmetic related, check signedness and width extension carefully.
- If the bug is control related, check reset and enable behavior carefully.
""".strip() + "\n"

def build_rtl_compile_feedback(module_name, module_data, stderr_text, category):
    signature = module_data["module_signature"]
    rules, lang = common_rtl_rules(signature)

    return f"""
The generated {lang} code failed to compile.

Module Name: {module_name}
Compilation error category: {category}

Compiler error:
{stderr_text}

Please fix the RTL and keep the exact same module signature.

{rules}

Additional guidance:
- Fix the specific compile issue first.
- Avoid introducing extra modules.
- Avoid changing port directions, parameter names, or widths.
- If the issue is with arrays or parameters, simplify the implementation while keeping the same interface.
CRITICAL:
- Output ONLY the corrected RTL code
- DO NOT explain anything
- DO NOT describe changes
- DO NOT reference files or paths
- Output must start with 'module'
- Output must end with 'endmodule'
""".strip() + "\n"

# Codex
def run_codex(prompt_file, output_file, preferred_module_name=None, attempts=3):
    prompt = prompt_file.read_text(encoding="utf-8").strip()
    last_error = None

    for _ in range(attempts):
        process = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", prompt],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(PROJECT_ROOT),
        )

        if process.returncode == 0:
            try:
                code = extract_single_module(process.stdout, preferred_name=preferred_module_name)
            except Exception:
                last_error = RuntimeError(
                    "Codex did not return valid RTL module.\n"
                    f"RAW OUTPUT:\n{process.stdout}"
                )
                continue

            save_text(output_file, code)
            return code

        last_error = RuntimeError(
            f"Codex failed:\nSTDOUT:\n{process.stdout}\n\nSTDERR:\n{process.stderr}"
        )

        err = (process.stderr or "").lower()
        if "selected model is at capacity" not in err:
            break

    raise last_error if last_error else RuntimeError("Codex failed without details.")

def get_clock_period(module_data):
    clk = module_data.get("clock_period", None)

    if clk is None:
        return OPENROAD_CLOCK_PERIOD  # fallback

    if isinstance(clk, str):
        m = re.search(r"(\d+\.?\d*)", clk)
        if m:
            return float(m.group(1))

    if isinstance(clk, (int, float)):
        return float(clk)

    return OPENROAD_CLOCK_PERIOD

# Python TB generators for known problems
def gen_tb_p1(module_name, module_data):
    stimulus = module_data["sample_input"].replace("_", "").strip()
    n = len(stimulus)

    lines = []
    lines.append("module tb;")
    lines.append("  reg clk;")
    lines.append("  reg reset;")
    lines.append("  reg data_in;")
    lines.append("  wire detected;")
    lines.append(f"  reg [{n-1}:0] stimulus;")
    lines.append("  integer i;")
    lines.append("")
    lines.append(f"  {module_name} uut (")
    lines.append("    .clk(clk),")
    lines.append("    .reset(reset),")
    lines.append("    .data_in(data_in),")
    lines.append("    .detected(detected)")
    lines.append("  );")
    lines.append("")
    lines.append("  always #5 clk = ~clk;")
    lines.append("")
    lines.append("  initial begin")
    lines.append("    clk = 0;")
    lines.append("    reset = 1;")
    lines.append("    data_in = 0;")
    lines.append(f"    stimulus = {n}'b{stimulus};")
    lines.append("    #10;")
    lines.append("    reset = 0;")
    lines.append("")
    lines.append(f"    for (i = {n-1}; i >= 0; i = i - 1) begin")
    lines.append("      data_in = stimulus[i];")
    lines.append("      @(posedge clk);")
    lines.append("      @(negedge clk);")
    lines.append('      $display("OBS detected=%b", detected);')
    lines.append("    end")
    lines.append("")
    lines.append("    #10;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def gen_tb_p7(module_name, module_data):
    usage = module_data["sample_usage"]
    width = extract_numeric(module_data["parameters"]["WIDTH"])

    rst_seq = safe_parse_sequence(usage.get("rst_sequence", [])) or []
    en_seq = safe_parse_sequence(usage.get("enable_sequence", [])) or []
    x_seq = safe_parse_sequence(usage.get("x_in_sequence", [])) or []
    expected = safe_parse_sequence(usage.get("expected_exp_out", [])) or []

    rst_seq = [int(x) for x in rst_seq]
    en_seq = [int(x) for x in en_seq]
    x_seq = [int(x) for x in x_seq]
    expected = [None if x is None else int(x) for x in expected]

    cycles = max(len(rst_seq), len(en_seq), len(x_seq), len(expected))

    lines = []
    lines.append("module tb;")
    lines.append(f"  localparam WIDTH = {width};")
    lines.append("  reg clk;")
    lines.append("  reg rst;")
    lines.append("  reg enable;")
    lines.append("  reg [WIDTH-1:0] x_in;")
    lines.append("  wire [2*WIDTH-1:0] exp_out;")
    lines.append("  integer cycle;")
    lines.append("")
    lines.append(f"  {module_name} #(.WIDTH(WIDTH)) uut (")
    lines.append("    .clk(clk), .rst(rst), .enable(enable), .x_in(x_in), .exp_out(exp_out)")
    lines.append("  );")
    lines.append("")
    lines.append("  always #5 clk = ~clk;")
    lines.append("")
    lines.append("  initial begin")
    lines.append("    clk = 0;")
    lines.append("    rst = 1;")
    lines.append("    enable = 0;")
    lines.append("    x_in = 0;")
    lines.append("    #10;")
    lines.append("    rst = 0;")
    lines.append("")
    lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")
    for idx in range(cycles):
        rst_v = rst_seq[idx] if idx < len(rst_seq) else 0
        en_v = en_seq[idx] if idx < len(en_seq) else 0
        x_v = x_seq[idx] if idx < len(x_seq) else 0
        lines.append(f"      if (cycle == {idx}) begin")
        lines.append(f"        rst = 1'b{rst_v};")
        lines.append(f"        enable = 1'b{en_v};")
        lines.append(f"        x_in = {int(x_v)};")
        lines.append("      end")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append('      $display("OBS exp_out=%0d", exp_out);')
    lines.append("      @(negedge clk);")
    lines.append("    end")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def gen_tb_p5(module_name, module_data):
    usage = module_data["sample_usage"]
    N = extract_numeric(module_data["parameters"]["N"])
    WIDTH = extract_numeric(module_data["parameters"]["WIDTH"])

    A_vals = normalize_list(peel_singletons(usage["A_sequence"]))
    B_vals = normalize_list(peel_singletons(usage["B_sequence"]))
    exp_valid = usage["expected_valid"]
    exp_dot = normalize_list(peel_singletons(usage["expected_dot_out"]))

    if not isinstance(A_vals, list) or not isinstance(B_vals, list):
        raise ValueError("Could not parse A/B sequences for dot_product TB.")

    cycles = len(exp_valid)

    lines = []
    lines.append("module tb;")
    lines.append(f"  localparam N = {N};")
    lines.append(f"  localparam WIDTH = {WIDTH};")
    lines.append("  logic clk;")
    lines.append("  logic rst;")
    lines.append("  logic signed [N-1:0][WIDTH-1:0] A;")
    lines.append("  logic signed [N-1:0][WIDTH-1:0] B;")
    lines.append("  logic signed [2*WIDTH+3:0] dot_out;")
    lines.append("  logic valid;")
    lines.append("  integer cycle;")
    lines.append("")
    lines.append(f"  {module_name} #(.N(N), .WIDTH(WIDTH)) uut (")
    lines.append("    .clk(clk), .rst(rst), .A(A), .B(B), .dot_out(dot_out), .valid(valid)")
    lines.append("  );")
    lines.append("")
    lines.append("  always #5 clk = ~clk;")
    lines.append("")
    lines.append("  initial begin")
    lines.append("    clk = 0;")
    lines.append("    rst = 1;")
    lines.append("    A = '0;")
    lines.append("    B = '0;")
    for idx, val in enumerate(A_vals):
        lines.append(f"    A[{idx}] = {int(val)};")
    for idx, val in enumerate(B_vals):
        lines.append(f"    B[{idx}] = {int(val)};")
    lines.append("    #10;")
    lines.append("    rst = 0;")
    lines.append("")
    lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append('      $display("OBS valid=%b dot_out=%0d", valid, dot_out);')
    lines.append("      @(negedge clk);")
    lines.append("    end")
    lines.append("")
    lines.append("    #10;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def gen_tb_p8(module_name, module_data):
    usage = module_data["sample_usage"]
    a_val = usage["a"].split("#")[0].strip().replace("_", "")
    b_val = usage["b"].split("#")[0].strip().replace("_", "")
    lines = []
    lines.append("module tb;")
    lines.append("  logic [15:0] a;")
    lines.append("  logic [15:0] b;")
    lines.append("  logic [15:0] result;")
    lines.append("")
    lines.append(f"  {module_name} uut (")
    lines.append("    .a(a), .b(b), .result(result)")
    lines.append("  );")
    lines.append("")
    lines.append("  initial begin")
    lines.append(f"    a = {a_val};")
    lines.append(f"    b = {b_val};")
    lines.append("    #1;")
    lines.append('    $display("OBS result=%b", result);')
    lines.append("    #1;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def infer_fir_coefficients(module_data, n):
    return list(range(1, n + 1))


def sv_sized_signed_literal(width, value):
    v = int(value)
    if v < 0:
        return f"-{width}'sd{abs(v)}"
    return f"{width}'sd{v}"


def gen_tb_fir_filter(module_name, module_data):
    params = module_data.get("parameters", {})
    width = extract_numeric(params.get("WIDTH", 16))
    n = extract_numeric(params.get("N", 8))

    stim = module_data.get("stimulus", {})
    expected = module_data.get("expected_y_out", []) or []

    rst_seq = safe_parse_sequence(stim.get("rst", [])) or []
    x_seq = safe_parse_sequence(stim.get("x_in", [])) or []
    coeffs = safe_parse_sequence(stim.get("h", [])) or infer_fir_coefficients(module_data, n)

    rst_seq = [int(v) for v in rst_seq]
    x_seq = [int(v) for v in x_seq]
    coeffs = [int(v) for v in coeffs[:n]]

    if len(coeffs) < n:
        coeffs += [0] * (n - len(coeffs))

    reset_cycles = 0
    while reset_cycles < len(rst_seq) and rst_seq[reset_cycles] == 1:
        reset_cycles += 1
    if reset_cycles == 0:
        reset_cycles = 1

    if not x_seq and expected:
        x_seq = [1] * len(expected)

    cycles = max(len(x_seq), len(expected), 1)

    coeff_concat = ", ".join(
        sv_sized_signed_literal(width, v) for v in reversed(coeffs)
    )

    lines = []
    lines.append("module tb;")
    lines.append(f"  localparam WIDTH = {width};")
    lines.append(f"  localparam N = {n};")
    lines.append("  reg clk;")
    lines.append("  reg rst;")
    lines.append("  reg signed [WIDTH-1:0] x_in;")
    lines.append("  reg signed [N-1:0][WIDTH-1:0] h;")
    lines.append("  wire signed [2*WIDTH+$clog2(N):0] y_out;")
    lines.append("  integer cycle;")
    lines.append("")
    lines.append(f"  {module_name} #(.WIDTH(WIDTH), .N(N)) uut (")
    lines.append("    .clk(clk), .rst(rst), .x_in(x_in), .h(h), .y_out(y_out)")
    lines.append("  );")
    lines.append("")
    lines.append("  always #5 clk = ~clk;")
    lines.append("")
    lines.append("  initial begin")
    lines.append("    clk = 0;")
    lines.append("    rst = 1;")
    lines.append("    x_in = 0;")
    lines.append(f"    h = {{{coeff_concat}}};")
    lines.append("")
    lines.append(f"    repeat ({reset_cycles}) begin")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append("    end")
    lines.append("    rst = 0;")
    lines.append("")
    lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")
    for idx in range(cycles):
        x_v = x_seq[idx] if idx < len(x_seq) else 0
        x_lit = sv_sized_signed_literal(width, x_v)
        lines.append(f"      if (cycle == {idx}) begin")
        lines.append(f"        x_in = {x_lit};")
        lines.append("      end")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append('      $display("OBS y_out=%0d", y_out);')
    lines.append("      @(negedge clk);")
    lines.append("    end")
    lines.append("")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")

    return "\n".join(lines) + "\n"

def is_sequential_design(module_data):
    ports = module_data.get("ports", [])

    for p in ports:
        name = p.get("name", "").lower()
        if name in {"clk", "clock"}:
            return True

    return False

def decl_for_port(p):
    name = p.get("name", "")
    direction = p.get("direction", "")
    width = str(p.get("width", "")).strip()
    signed = bool(p.get("signed", False))

    base = "reg" if direction == "input" else "wire"
    signed_kw = " signed" if signed else ""

    # normalize WIDTH properly
    if width:
        if "[" not in width:
            # assume scalar width like WIDTH  (convert to [WIDTH-1:0])
            width = f"[{width}-1:0]"
        return f"  {base}{signed_kw} {width} {name};"

    return f"  {base}{signed_kw} {name};"

def build_post_synth_feedback_prompt(
    module_name,
    module_data,
    expected_text,
    actual_text,
    synth_log_tail="",
    post_synth_log_tail="",
    rtl_text="",
):
    signature = module_data["module_signature"]
    rules, lang = common_rtl_rules(signature)

    return f"""
The RTL passed the initial test, but the synthesized netlist failed the post-synthesis check.

Module Name: {module_name}
Description: {module_data.get("description", "")}

Important:
- Edit the ORIGINAL RTL source only.
- Do NOT edit the synthesized netlist.
- Keep the exact same module signature.
- Preserve synthesizability.

Expected behavior:
{expected_text}

Actual post-synthesis behavior:
{actual_text}

Synthesis log tail:
{synth_log_tail}

Post-synthesis simulation log tail:
{post_synth_log_tail}

Current RTL:
{rtl_text}

Please diagnose the RTL issue that causes the synthesized netlist to behave incorrectly.
Focus on sequential behavior, reset behavior, signedness, and any constructs that may synthesize differently than intended.

{rules}

Additional guidance:
- Avoid blocking assignments in sequential always blocks.
- Avoid inferred latches.
- Check reset polarity and reset timing carefully.
- Check pipeline latency carefully.
- Check signed arithmetic and width extension carefully.
- Keep the module interface unchanged.
- Fix synthesis issues related to reset style and latch inference.
- Ensure synchronous reset and fully specified combinational logic.
CRITICAL:
- Output ONLY the corrected RTL code
- DO NOT explain anything
- DO NOT describe changes
- DO NOT reference files or paths
- Output must start with 'module'
- Output must end with 'endmodule'
""".strip() + "\n"

def evaluate_pwm(module_data, sim_output):
    usage = module_data.get("sample_usage", {})

    expected_high = usage.get("expected_high_cycles")
    expected_low = usage.get("expected_low_cycles")

    if expected_high is None or expected_low is None:
        return None

    pwm_vals = [int(x) for x in re.findall(r"OBS pwm_out=(\d+)", sim_output)]

    if not pwm_vals:
        return False, "No PWM output", ""

    high_count = sum(pwm_vals)
    low_count = len(pwm_vals) - high_count

    passed = (high_count == expected_high) and (low_count == expected_low)

    expected_text = f"high={expected_high}, low={expected_low}"
    actual_text = f"high={high_count}, low={low_count}"

    return passed, expected_text, actual_text

def build_testcase_tb(module_name, module_data, ports, test_cases):
    lines = []
    lines.append("module tb;")

    params = module_data.get("parameters", {})
    for k, v in params.items():
        lines.append(f"  localparam {k} = {v};")

    lines.append("")

    # Declare ports
    for p in ports:
        lines.append(decl_for_port(p))

    lines.append("")

    # DUT instantiation
    if params:
        param_map = ", ".join([f".{k}({k})" for k in params])
        lines.append(f"  {module_name} #({param_map}) uut (")
    else:
        lines.append(f"  {module_name} uut (")

    port_map = ",\n    ".join([f".{p['name']}({p['name']})" for p in ports])
    lines.append(f"    {port_map}")
    lines.append("  );\n")

    lines.append("  initial begin")

    for i, tc in enumerate(test_cases):
        lines.append(f"\n    // Test case {i}")

        # Apply inputs
        for k, v in tc.items():
            if not k.startswith("expected_"):
                lines.append(f"    {k} = {v};")

        lines.append("    #1;")

        # Print outputs
        for k, v in tc.items():
            if k.startswith("expected_"):
                out = k.replace("expected_", "")
                lines.append(f'    $display("OBS {out}=%0d", {out});')

    lines.append("\n    #10;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")

    return "\n".join(lines) + "\n"

def build_generic_testbench(module_name, module_data):
    test_cases = module_data.get("sample_usage", {}).get("test_cases", None)
    ports = module_data.get("ports") or []
    if not ports:
        signature = module_data.get("module_signature", "")
        ports = parse_port_decls_from_signature(signature)
    test_cases = module_data.get("sample_usage", {}).get("test_cases", None)

    if test_cases:
        return build_testcase_tb(module_name, module_data, ports, test_cases)
    params = module_data.get("parameters", {})

    input_ports = []
    output_ports = []
    has_clk = False
    has_rst = False

    for p in ports:
        name = p.get("name", "")
        direction = p.get("direction", "")

        if name == "clk":
            has_clk = True
        if name in {"rst", "reset"}:
            has_rst = True

        if direction == "input":
            input_ports.append(name)
        elif direction == "output":
            output_ports.append(name)

    # Build sequences
    sequences = {}
    constant_inputs = {}

    for name in input_ports:
        seq = find_sequence_for_port(name, module_data)

        if seq is not None:
            # Detect constant inputs
            if len(seq) > 0 and len(set(map(str, seq))) == 1:
                constant_inputs[name] = seq[0]
            else:
                sequences[name] = seq

    cycles = max([len(v) for v in sequences.values()], default=DEFAULT_GENERIC_CYCLES)

    lines = []
    lines.append("module tb;")

    # Parameters (SAFE) 
    for k, v in params.items():
        lines.append(f"  localparam {k} = {v};")

    lines.append("")

    # Port declarations 
    for p in ports:
        lines.append(decl_for_port(p))

    lines.append("")

    # DUT instantiation 
    if params:
        param_map = ", ".join([f".{k}({k})" for k in params])
        lines.append(f"  {module_name} #({param_map}) uut (")
    else:
        lines.append(f"  {module_name} uut (")

    port_map = ",\n    ".join([f".{p['name']}({p['name']})" for p in ports])
    lines.append(f"    {port_map}")
    lines.append("  );\n")

    # Clock 
    if has_clk:
        lines.append("  always #5 clk = ~clk;\n")

    lines.append("  integer cycle;\n")

    # Initial block 
    lines.append("  initial begin")

    # init inputs
    for name in input_ports:
        if name != "clk":
            if name in constant_inputs:
                lines.append(f"    {name} = {format_sv_value(constant_inputs[name])};")
            else:
                lines.append(f"    {name} = 0;")

    if has_clk:
        lines.append("    clk = 0;")

    if has_rst:
        if "rst" in input_ports:
            lines.append("    rst = 1;")
        elif "reset" in input_ports:
            lines.append("    reset = 1;")

    lines.append("    #10;")

    if has_rst:
        if "rst" in input_ports:
            lines.append("    rst = 0;")
        elif "reset" in input_ports:
            lines.append("    reset = 0;")

    lines.append("")

    # Simulation loop 
    if has_clk:
        lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")

        for i in range(cycles):
            lines.append(f"      if (cycle == {i}) begin")
            for name in input_ports:
                if name == "clk":
                    continue

                # Skip constant inputs
                if name in constant_inputs:
                    continue

                if name in sequences and i < len(sequences[name]):
                    lines.append(f"        {name} = {format_sv_value(sequences[name][i])};")
            lines.append("      end")

        lines.append("      @(posedge clk);")
        lines.append("      #1;")

        for name in output_ports:
            lines.append(f'      $display("OBS {name}=%0d", {name});')

        lines.append("      @(negedge clk);")
        lines.append("    end")
    else:
        # combinational
        for name in input_ports:
            if name in sequences and sequences[name]:
                lines.append(f"    {name} = {format_sv_value(sequences[name][0])};")

        lines.append("    #1;")

        for name in output_ports:
            lines.append(f'    $display("OBS {name}=%0d", {name});')

    lines.append("\n    #10;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")

    return "\n".join(lines) + "\n"

def sanity_check_outputs(sim_output):
    values = re.findall(r"OBS .*?=(-?\d+)", sim_output)

    if not values:
        return False  # no outputs at all

    unique_vals = set(values)

    #  Stuck output
    if len(unique_vals) == 1:
        return False

    return True

def generate_testbench(module_name, module_data, force_generic=False):
    if module_name == "fir_filter":
        return gen_tb_fir_filter(module_name, module_data)

    if force_generic:
        return build_generic_testbench(module_name, module_data)

    if module_name == "seq_detector_0011":
        return gen_tb_p1(module_name, module_data)
    if module_name == "dot_product":
        return gen_tb_p5(module_name, module_data)
    if module_name == "exp_fixed_point":
        return gen_tb_p7(module_name, module_data)
    if module_name == "fp16_multiplier":
        return gen_tb_p8(module_name, module_data)

    return build_generic_testbench(module_name, module_data)


# Simulation
def run_simulation(rtl_file, tb_file):
    compile_cmd = [
        "iverilog",
        "-g2012",
        "-o",
        str(GEN_DIR / "sim.out"),
        str(rtl_file),
        str(tb_file),
    ]
    run_cmd = ["vvp", str(GEN_DIR / "sim.out")]

    compile_result = subprocess.run(
        compile_cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if compile_result.returncode != 0:
        return {
            "compile_ok": False,
            "compile_stderr": compile_result.stderr,
            "sim_output": "",
            "sim_stderr": "",
        }

    run_result = subprocess.run(
        run_cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    return {
        "compile_ok": True,
        "compile_stderr": "",
        "sim_output": run_result.stdout,
        "sim_stderr": run_result.stderr,
    }


# Evaluation helpers
def evaluate_p1(module_data, sim_output):
    expected = module_data["sample_output"]
    actual_bits = re.findall(r"OBS detected=(\d)", sim_output)
    actual = "".join(actual_bits)
    return actual == expected, expected, actual


def evaluate_p5(module_data, sim_output):
    usage = module_data["sample_usage"]
    exp_valid = usage["expected_valid"]
    exp_dot = normalize_list(peel_singletons(usage["expected_dot_out"]))
    if not isinstance(exp_dot, list):
        exp_dot = [exp_dot]

    matches = re.findall(r"OBS valid=(\d) dot_out=(-?\d+)", sim_output)
    actual_valid = [int(v) for v, _ in matches]
    actual_dot_valid_cycles = [int(d) for v, d in matches if int(v) == 1]

    expected_text = f"valid={exp_valid}, dot_out_on_valid={exp_dot}"
    actual_text = f"valid={actual_valid}, dot_out_on_valid={actual_dot_valid_cycles}"

    passed = (actual_valid == exp_valid) and (actual_dot_valid_cycles == exp_dot)
    return passed, expected_text, actual_text


def first_non_none_index(seq):
    for i, v in enumerate(seq):
        if v is not None:
            return i
    return None


def evaluate_p7(module_data, sim_output):
    usage = module_data["sample_usage"]
    expected_seq = usage["expected_exp_out"]
    actual_vals = [int(x) for x in re.findall(r"OBS exp_out=(\d+)", sim_output)]

    if len(actual_vals) < len(expected_seq):
        return False, f"exp_out={expected_seq}", f"exp_out={actual_vals}"

    for idx, exp in enumerate(expected_seq):
        if exp is None:
            continue
        if actual_vals[idx] != int(exp):
            return False, f"exp_out={expected_seq}", f"exp_out={actual_vals}"

    return True, f"exp_out={expected_seq}", f"exp_out={actual_vals}"


def evaluate_p8(module_data, sim_output):
    usage = module_data["sample_usage"]
    expected = usage["result"].split("#")[0].strip().replace("_", "").replace("16'b", "")
    m = re.search(r"OBS result=([01]+)", sim_output)
    actual = m.group(1) if m else ""
    return actual == expected, expected, actual


def evaluate_fir_filter(module_data, sim_output):
    expected = module_data.get("expected_y_out", [])
    if not isinstance(expected, list):
        expected = []

    actual_vals = [int(x) for x in re.findall(r"OBS y_out\s*=\s*(-?\d+)", sim_output)]

    if len(actual_vals) < len(expected):
        return False, f"y_out={expected}", f"y_out={actual_vals}"

    actual_prefix = actual_vals[:len(expected)]
    if actual_prefix != expected:
        return False, f"y_out={expected}", f"y_out_prefix={actual_prefix}, full={actual_vals}"

    return True, f"y_out={expected}", f"y_out_prefix={actual_prefix}"


def evaluate_generic_problem(module_name, module_data, sim_output):
    ports = module_data.get("ports") or []
    if not ports:
        signature = module_data.get("module_signature", "")
        ports = parse_port_decls_from_signature(signature)

    output_ports = [p.get("name", "") for p in ports if p.get("direction", "") == "output"]

    if not output_ports:
        return None

    results = []
    all_passed = True

    for out_name in output_ports:
        expected = find_expected_values_for_output(module_data, out_name)
        if expected is None:
            continue

        pattern = rf"OBS {re.escape(out_name)}=(-?\d+)"
        actual_vals = [int(x) for x in re.findall(pattern, sim_output)]

        if not actual_vals:
            all_passed = False
            results.append((out_name, expected, actual_vals))
            continue

        # LATENCY-TOLERANT MATCH
        match_found = False

        for shift in range(len(actual_vals)):
            window = actual_vals[shift:shift+len(expected)]
            if window == expected:
                match_found = True
                break

        if not match_found:
            all_passed = False

        results.append((out_name, expected, actual_vals))

    if not results:
        return None

    expected_text = "; ".join([f"{n}={e}" for n, e, _ in results])
    actual_text = "; ".join([f"{n}={a}" for n, _, a in results])

    return all_passed, expected_text, actual_text

def evaluate_problem(module_name, module_data, sim_output):
    if module_name == "seq_detector_0011":
        return evaluate_p1(module_data, sim_output)
    if module_name == "dot_product":
        return evaluate_p5(module_data, sim_output)
    if module_name == "exp_fixed_point":
        return evaluate_p7(module_data, sim_output)
    if module_name == "fp16_multiplier":
        return evaluate_p8(module_data, sim_output)
    if module_name == "fir_filter":
        return evaluate_fir_filter(module_data, sim_output)
    if module_name == "pwm_generator":
        return evaluate_pwm(module_data, sim_output)
    generic_eval = evaluate_generic_problem(module_name, module_data, sim_output)
    if generic_eval is not None:
        return generic_eval

    return None

def evaluate_visible_tb(problem_stem, sim_output):

    if problem_stem == "p1":
        return ("Test PASSED" in sim_output, "official TB", sim_output[-200:])

    if problem_stem == "p5":
        return ("PASS: Output" in sim_output, "official TB", sim_output[-200:])

    if problem_stem == "p7":
        return ("PASS" in sim_output, "official TB", sim_output[-200:])

    if problem_stem == "p8":
        # Check if ANY FAIL exists
        if "FAIL" in sim_output:
            return False, "official TB", sim_output[-200:]

        # Must have at least one PASS
        if "PASS" in sim_output:
            return True, "official TB", sim_output[-200:]

        return False, "official TB", sim_output[-200:]

    if problem_stem == "p9":
        pairs = re.findall(r"y_out\s*=\s*(-?\d+).*?expected\s*=\s*(-?\d+)", sim_output)

        if not pairs:
            return False, "official TB", sim_output[-200:]

        all_pass = True
        for actual, expected in pairs:
            if int(actual) != int(expected):
                all_pass = False
                break

        # Extract only valid lines
        clean_lines = re.findall(r"y_out\s*=\s*-?\d+.*?expected\s*=\s*-?\d+", sim_output)

        if not clean_lines:
            return False, "official TB", "No valid FIR outputs found"

        summary = "\n".join(clean_lines[-3:])  # show last few valid samples

        return all_pass, "official TB", summary

    return False, "official TB", sim_output[-200:]

def setup_openroad_design(problem_stem, module_name, module_data, rtl_src):
    design_dir = OPENROAD_FLOW_ROOT / "designs" / OPENROAD_PLATFORM / problem_stem
    design_dir.mkdir(parents=True, exist_ok=True)

    # Copy RTL
    rtl_dst = design_dir / "design.sv"
    shutil.copy2(rtl_src, rtl_dst)

    # Get clock period from YAML
    clock_period = get_clock_period(module_data)

    # Create SDC
    sdc_text = f"""
create_clock -name clk -period {clock_period} [get_ports clk]
"""
    save_text(design_dir / "constraint.sdc", sdc_text)

    # Create config.mk
    config_text = f"""
export DESIGN_NAME = {module_name}
export PLATFORM = {OPENROAD_PLATFORM}
export VERILOG_FILES = /work/designs/{OPENROAD_PLATFORM}/{problem_stem}/design.sv
export SDC_FILE = /work/designs/{OPENROAD_PLATFORM}/{problem_stem}/constraint.sdc
export CLOCK_PORT = clk
export CLOCK_PERIOD = {clock_period}
export SKIP_CTS_REPAIR_TIMING = 1

export CORE_UTILIZATION = {OPENROAD_CORE_UTILIZATION}
export PLACE_DENSITY = {OPENROAD_PLACE_DENSITY}
"""
    save_text(design_dir / "config.mk", config_text)

    return design_dir

def clean_openroad_run(module_name):
    for sub in ["results", "logs", "objects"]:
        path = OPENROAD_FLOW_ROOT / sub / OPENROAD_PLATFORM / module_name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def run_openroad_synth_only(problem_stem, module_name):
    design_config = f"/work/designs/{OPENROAD_PLATFORM}/{problem_stem}/config.mk"
    cmd = (
        f"cd {OPENROAD_FLOW_ROOT} && "
        f"util/docker_shell make PLATFORM={OPENROAD_PLATFORM} "
        f"DESIGN_NAME={module_name} DESIGN_CONFIG={design_config} synth"
    )
    return subprocess.run(
        ["bash", "-lc", cmd],
        cwd=str(OPENROAD_FLOW_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

def evaluate_testcases(module_data, sim_output):
    test_cases = module_data.get("sample_usage", {}).get("test_cases")
    if not test_cases:
        return None

    observed = re.findall(r"OBS (\w+)=(-?\d+)", sim_output)

    if not observed:
        return False, "No outputs observed", ""

    outputs_by_name = {}
    for name, val in observed:
        outputs_by_name.setdefault(name, []).append(int(val))

    expected_text = []
    actual_text = []

    all_passed = True

    for tc in test_cases:
        for k, v in tc.items():
            if k.startswith("expected_"):
                out = k.replace("expected_", "")

                expected_val = int(str(v).replace("16'h",""), 16) if "h" in str(v) else int(v)

                actual_vals = outputs_by_name.get(out, [])

                if expected_val not in actual_vals:
                    all_passed = False

                expected_text.append(f"{out}={expected_val}")
                actual_text.append(f"{out}={actual_vals}")

    return all_passed, ", ".join(expected_text), ", ".join(actual_text)

def get_post_synth_netlist_path(module_name):
    base = OPENROAD_FLOW_ROOT / "results" / OPENROAD_PLATFORM / module_name / "base"
    candidates = [
        base / "1_2_yosys.v",
        base / "1_synth.v",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]

def find_sky130_model_file():
    search_roots = [
        OPENROAD_FLOW_ROOT,
        Path.home() / "OpenROAD-flow-scripts",
    ]

    for root in search_roots:
        for p in root.rglob("*.v"):
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if "module sky130_fd_sc_hd__dfxtp_1" in txt and "module sky130_fd_sc_hd__and3b_1" in txt:
                return p

    return None

def make_post_synth_tb_text(tb_text):
    """
    Robust parser for post-synthesis TB.
    Converts parameterized instantiation into plain instantiation.
    """

    text = tb_text

    # Remove parameter block safely (multi-line)
    text = re.sub(
        r"(\w+)\s*#\s*\([\s\S]*?\)\s*(\w+)\s*\(",
        r"\1 \2 (",
        text
    )

    # Replace SystemVerilog keywords (safe for iverilog)
    text = re.sub(r"\blogic\b", "reg", text)

    return text

def run_post_synth_check(problem_stem, module_name, tb_file):
    synth_v = get_post_synth_netlist_path(module_name)
    if not synth_v.exists():
        return False, f"Missing synthesized netlist: {synth_v}", ""

    model_file = find_sky130_model_file()
    if model_file is None:
        return False, "Could not find Sky130HD Verilog cell models for post-synthesis simulation.", ""

    out_file = GEN_DIR / problem_stem / "post_synth.out"
    post_tb = GEN_DIR / problem_stem / "post_synth_tb.sv"

    tb_text = tb_file.read_text(encoding="utf-8")
    post_tb_text = make_post_synth_tb_text(tb_text)
    save_text(post_tb, post_tb_text)

    compile_cmd = [
        "iverilog",
        "-g2012",
        "-o",
        str(out_file),
        str(model_file),
        str(synth_v),
        str(post_tb),
    ]

    compile_result = subprocess.run(
        compile_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_result.returncode != 0:
        return False, compile_result.stderr, ""

    run_result = subprocess.run(
        ["vvp", str(out_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    return True, run_result.stdout, run_result.stderr



def run_openroad_flow(problem_stem, module_name):
    design_config = f"/work/designs/{OPENROAD_PLATFORM}/{problem_stem}/config.mk"
    cmd = (
        f"cd {OPENROAD_FLOW_ROOT} && "
        f"util/docker_shell make PLATFORM={OPENROAD_PLATFORM} "
        f"DESIGN_NAME={module_name} DESIGN_CONFIG={design_config}"
    )
    return subprocess.run(
        ["bash", "-lc", cmd],
        cwd=str(OPENROAD_FLOW_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def copy_openroad_results(problem_stem, module_name):
    src_dir = OPENROAD_FLOW_ROOT / "results" / OPENROAD_PLATFORM / module_name / "base"
    dst_dir = GEN_DIR / problem_stem / "openroad"

    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    if src_dir.exists():
        for f in src_dir.iterdir():
            if f.is_file():
                # Rename GDS for clarity
                if f.name == "6_final.gds":
                    shutil.copy2(f, dst_dir / f"{module_name}.gds")

                # Copy timing report with better name
                elif f.name == "timing.rpt":
                    shutil.copy2(f, dst_dir / "timing.rpt")

                # Copy everything else as-is
                else:
                    shutil.copy2(f, dst_dir / f.name)
    # Force copy timing report
    timing_src = src_dir / "timing.rpt"
    if timing_src.exists():
        shutil.copy2(timing_src, dst_dir / "timing.rpt")
        print(f"[{module_name}] timing.rpt copied")
    else:
        print(f"[{module_name}] timing.rpt NOT found")               
def get_final_gds_path(module_name):
    return OPENROAD_FLOW_ROOT / "results" / OPENROAD_PLATFORM / module_name / "base" / "6_final.gds"

def tail_text(text, max_lines=40, max_chars=4000):
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    out = "\n".join(lines)
    return out[-max_chars:]

def print_post_synth_report(problem_stem, expected_text, actual_text, post_stdout=""):
    print(f"[{problem_stem}] POST-SYNTH Expected:", expected_text)
    print(f"[{problem_stem}] POST-SYNTH Actual  :", actual_text)
    if post_stdout:
        print(f"[{problem_stem}] POST-SYNTH Output tail:")
        print(tail_text(post_stdout, max_lines=20, max_chars=2500))

def extract_timing_metrics(module_name):
    rpt = OPENROAD_FLOW_ROOT / "results" / OPENROAD_PLATFORM / module_name / "base" / "timing.rpt"
    
    if not rpt.exists():
        return None, None
    
    text = rpt.read_text()

    wns = None
    tns = None

    # More robust parsing
    m1 = re.search(r"worst slack max\s+(-?\d+\.?\d*)", text)
    m2 = re.search(r"tns max\s+(-?\d+\.?\d*)", text)

    if m1:
        wns = float(m1.group(2))
    if m2:
        tns = float(m2.group(2))

    return wns, tns

def generate_timing_report(module_name):
    base = OPENROAD_FLOW_ROOT / "results" / OPENROAD_PLATFORM / module_name / "base"
    tcl = base / "timing.tcl"
    rpt = base / "timing.rpt"

    tcl_text = f"""
read_liberty /work/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_db /work/results/{OPENROAD_PLATFORM}/{module_name}/base/6_final.odb
read_sdc /work/results/{OPENROAD_PLATFORM}/{module_name}/base/6_final.sdc
read_spef /work/results/{OPENROAD_PLATFORM}/{module_name}/base/6_final.spef

report_worst_slack
report_tns

report_checks -path_delay max -digits 4 > /work/results/{OPENROAD_PLATFORM}/{module_name}/base/timing.rpt

exit
"""
    save_text(tcl, tcl_text)

    cmd = f"""
cd {OPENROAD_FLOW_ROOT} && \
util/docker_shell openroad /work/results/{OPENROAD_PLATFORM}/{module_name}/base/timing.tcl
"""

    result = subprocess.run(
        ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
    )

    output = result.stdout + "\n" + result.stderr

    # Only print useful timing lines (optional debug)
    for line in output.splitlines():
        if "slack" in line.lower() or "tns" in line.lower():
            print(line) 

    # Extract directly from stdout instead of file
    m1 = re.search(r"worst slack max\s+(-?\d+\.?\d*)", output, re.IGNORECASE)
    m2 = re.search(r"tns max\s+(-?\d+\.?\d*)", output, re.IGNORECASE)

    wns = float(m1.group(1)) if m1 else None
    tns = float(m2.group(1)) if m2 else None

    return True, wns, tns

# Main flow
if len(sys.argv) > 1:
    yaml_files = [PROBLEMS_DIR / sys.argv[1]]
else:
    yaml_files = sorted(PROBLEMS_DIR.glob("*.yaml"))
summary = []

if not yaml_files:
    print("No YAML files found in problems/")
    raise SystemExit(1)

for yaml_file in yaml_files:
    print("\n==============================")
    print(f"PROCESSING: {yaml_file.name}")
    print("==============================\n")

    problem_stem = yaml_file.stem
    problem_gen_dir = GEN_DIR / problem_stem
    problem_prompt_dir = PROMPTS_DIR / problem_stem
    problem_log_dir = LOGS_DIR / problem_stem

    problem_gen_dir.mkdir(parents=True, exist_ok=True)
    problem_prompt_dir.mkdir(parents=True, exist_ok=True)
    problem_log_dir.mkdir(parents=True, exist_ok=True)

    rtl_file = problem_gen_dir / "design.sv"
    tb_file = problem_gen_dir / "tb.sv"

    rtl_prompt_file = problem_prompt_dir / "rtl_prompt.txt"
    rtl_feedback_file = problem_prompt_dir / "rtl_feedback.txt"

    status_file = problem_log_dir / "status.txt"
    sim_log_file = problem_log_dir / "simulation_output.txt"

    try:
        module_name, module_data = read_yaml_safe(yaml_file)
    except Exception as e:
        print(f"YAML parse failed: {e}")
        save_text(status_file, f"SKIPPED: YAML parse error\n{e}\n")
        summary.append(f"{problem_stem}: SKIPPED (YAML parse error)")
        continue

    rtl_prompt = build_rtl_prompt(module_name, module_data)
    save_text(rtl_prompt_file, rtl_prompt)

    current_rtl_prompt_file = rtl_prompt_file
    rtl_needs_gen = True
    use_generic_tb = False
    passed = False

    # PRIORITY: test-case driven TB
# PRIORITY: visible TB FIRST

    if problem_stem in VISIBLE_TB_MAP:
        tb_src = VISIBLE_TB_DIR / VISIBLE_TB_MAP[problem_stem]

        if tb_src.exists():
            shutil.copy2(tb_src, tb_file)
            print(f"Using official testbench: {tb_src.name}")
        else:
            raise FileNotFoundError(f"Missing TB: {tb_src}")

    else:
        # fallback to your existing logic (DO NOT change this)
        test_cases = module_data.get("sample_usage", {}).get("test_cases")

        if test_cases:
            ports = module_data.get("ports") or parse_port_decls_from_signature(
                module_data.get("module_signature","")
            )
            tb_code = build_testcase_tb(module_name, module_data, ports, test_cases)
        else:
            tb_code = generate_testbench(module_name, module_data, force_generic=use_generic_tb)

        save_text(tb_file, tb_code)
    for iteration in range(1, MAX_ITERS + 1):
        print(f"Iteration {iteration}")

        if rtl_needs_gen:
            try:
                rtl_code = run_codex(current_rtl_prompt_file, rtl_file, preferred_module_name=module_name)
                save_text(problem_gen_dir / f"design_iter{iteration}.sv", rtl_code)
                rtl_needs_gen = False
            except Exception as e:
                print(f"RTL generation failed: {e}")
                save_text(status_file, f"FAIL: RTL generation error\n{e}\n")
                summary.append(f"{problem_stem}: FAIL (RTL Codex error)")
                break

        sim_result = run_simulation(rtl_file, tb_file)

        if not sim_result["compile_ok"]:
            print("Compilation Failed")
            print(sim_result["compile_stderr"])
            save_text(sim_log_file, "Compilation Failed\n\n" + sim_result["compile_stderr"])

            category = classify_compile_error(sim_result["compile_stderr"])
            target = infer_compile_target(sim_result["compile_stderr"])

            if target == "tb" and not use_generic_tb:
                use_generic_tb = True
                tb_code = generate_testbench(module_name, module_data, force_generic=True)
                save_text(tb_file, tb_code)
                save_text(problem_gen_dir / f"tb_iter{iteration}.sv", tb_code)
                save_text(
                    status_file,
                    f"FAIL: TB compilation error (switched to generic TB fallback)\n{sim_result['compile_stderr']}\n"
                )
                continue

            rtl_feedback = build_rtl_compile_feedback(
                module_name,
                module_data,
                sim_result["compile_stderr"],
                category,
            )
            save_text(rtl_feedback_file, rtl_feedback)
            current_rtl_prompt_file = rtl_feedback_file
            rtl_needs_gen = True
            save_text(
                status_file,
                f"FAIL: RTL compilation error\n{sim_result['compile_stderr']}\n"
            )
            continue

        save_text(
            sim_log_file,
            sim_result["sim_output"]
            + ("\n--- STDERR ---\n" + sim_result["sim_stderr"] if sim_result["sim_stderr"] else "")
        )

        if problem_stem in VISIBLE_TB_MAP:
            eval_result = evaluate_visible_tb(problem_stem, sim_result["sim_output"])
        else:
            eval_result = evaluate_problem(module_name, module_data, sim_result["sim_output"])

            if eval_result is None:
                eval_result = evaluate_testcases(module_data, sim_result["sim_output"])
        #  Sanity check for hidden cases
        if eval_result is None:
            if not sanity_check_outputs(sim_result["sim_output"]):
                print("Output stuck or invalid → fixing RTL")

                rtl_feedback = f"""
        The RTL compiles but produces constant or invalid outputs.

        Fix the design so outputs respond to inputs.

        {common_rtl_rules(module_data["module_signature"])[0]}
        """
                save_text(rtl_feedback_file, rtl_feedback)
                current_rtl_prompt_file = rtl_feedback_file
                rtl_needs_gen = True
                continue
        if eval_result is not None:
            passed_now, expected_text, actual_text = eval_result
            print("Expected:", expected_text)
            print("Actual  :", actual_text)

            if passed_now:
                print("PASS\n")
                save_text(
                    status_file,
                    f"PASS\nIterations: {iteration}\nExpected: {expected_text}\nActual  : {actual_text}\n"
                )

                # 1) Run synthesis-only stage
                clean_openroad_run(module_name)
                setup_openroad_design(problem_stem, module_name, module_data, rtl_file)

                synth_result = run_openroad_synth_only(problem_stem, module_name)
                synth_log_file = problem_log_dir / "openroad_synth_output.txt"
                save_text(
                    synth_log_file,
                    synth_result.stdout + ("\n--- STDERR ---\n" + synth_result.stderr if synth_result.stderr else "")
                )

                if synth_result.returncode != 0:
                    print("Synthesis failed")
                    print(synth_result.stderr)

                    synth_tail = tail_text(
                        synth_result.stdout + "\n--- STDERR ---\n" + synth_result.stderr,
                        max_lines=30,
                        max_chars=4000,
                    )
                    rtl_text = rtl_file.read_text(encoding="utf-8")

                    rtl_feedback = f"""
                The RTL passed simulation, but OpenROAD/Yosys synthesis failed.

                Module Name: {module_name}
                Error:
                {synth_tail}

                Please fix the RTL so it synthesizes cleanly.

                Edit the ORIGINAL RTL only.
                Do NOT edit the synthesized netlist.
                Keep the exact same module signature.
                Focus on latch inference, incomplete combinational assignments, and unsupported constructs.

                Current RTL:
                {rtl_text}
Additional rules:
- Avoid inferred latches completely
- Do not use always_comb with partial assignments
- Assign all outputs in every branch
- Prefer assign statements over procedural loops
- Avoid loops inside combinational blocks
                """.strip() + "\n"

                    save_text(rtl_feedback_file, rtl_feedback)
                    current_rtl_prompt_file = rtl_feedback_file
                    rtl_needs_gen = True

                    save_text(
                        status_file,
                        f"SYNTH_FAIL\nIteration: {iteration}\n{synth_result.stderr}\n"
                    )
                    save_text(problem_log_dir / "synth_fail_tail.txt", synth_tail)
                    continue

                # 2) Run post-synthesis simulation
                post_ok, post_stdout, post_stderr = run_post_synth_check(problem_stem, module_name, tb_file)
                post_synth_log = problem_log_dir / "post_synth_output.txt"
                save_text(
                    post_synth_log,
                    post_stdout + ("\n--- STDERR ---\n" + post_stderr if post_stderr else "")
                )

                if not post_ok:
                    print(f"[{problem_stem}] Post-synthesis simulation execution failed")
                    print(f"[{problem_stem}] POST-SYNTH Output tail:")
                    print(tail_text(post_stdout, max_lines=20, max_chars=2500))    
                    rtl_text = rtl_file.read_text(encoding="utf-8")
                    synth_tail = tail_text(synth_result.stdout, max_lines=25, max_chars=2500)
                    post_tail = tail_text(post_stdout, max_lines=25, max_chars=2500)

                    rtl_feedback = build_post_synth_feedback_prompt(
                        module_name,
                        module_data,
                        "Post-synthesis simulation error",
                        post_tail,
                        synth_log_tail=synth_tail,
                        post_synth_log_tail=post_tail,
                        rtl_text=rtl_text[:6000],
                    )
                    save_text(rtl_feedback_file, rtl_feedback)
                    current_rtl_prompt_file = rtl_feedback_file
                    rtl_needs_gen = True

                    save_text(
                        status_file,
                        f"POST_SYNTH_FAIL\nIteration: {iteration}\nOutput:\n{post_tail}\n"
                    )
                    continue

                if problem_stem in VISIBLE_TB_MAP:
                    post_eval = evaluate_visible_tb(problem_stem, post_stdout)
                else:
                    post_eval = evaluate_problem(module_name, module_data, post_stdout)

                    if post_eval is None:
                        post_eval = evaluate_testcases(module_data, post_stdout)

                if post_eval is not None:
                    post_passed, post_expected_text, post_actual_text = post_eval
                    print("\n--- POST-SYNTH CHECK ---")
                    print("Expected:", post_expected_text)
                    print("Actual  :", post_actual_text)

                    if post_passed:
                        print("POST-SYNTH PASS\n")
                    else:
                        print("POST-SYNTH FAIL\n")


                    if not post_passed:
                        rtl_text = rtl_file.read_text(encoding="utf-8")
                        synth_tail = tail_text(synth_result.stdout, max_lines=25, max_chars=2500)
                        post_tail = tail_text(post_stdout, max_lines=25, max_chars=2500)

                        rtl_feedback = build_post_synth_feedback_prompt(
                            module_name,
                            module_data,
                            post_expected_text,
                            post_actual_text,
                            synth_log_tail=synth_tail,
                            post_synth_log_tail=post_tail,
                            rtl_text=rtl_text[:6000],
                        )
                        save_text(rtl_feedback_file, rtl_feedback)
                        current_rtl_prompt_file = rtl_feedback_file
                        rtl_needs_gen = True

                        save_text(
                            status_file,
                            f"POST_SYNTH_FAIL\nIteration: {iteration}\nExpected: {post_expected_text}\nActual  : {post_actual_text}\n"
                        )
                        continue
                else:
                    print(f"[{problem_stem}] POST-SYNTH could not be evaluated")
                    print(tail_text(post_stdout))
                # 3) Run full OpenROAD flow
                or_result = run_openroad_flow(problem_stem, module_name)
                or_log_file = problem_log_dir / "openroad_output.txt"
                save_text(
                    or_log_file,
                    or_result.stdout + ("\n--- STDERR ---\n" + or_result.stderr if or_result.stderr else "")
                )

                gds_path = get_final_gds_path(module_name)
                if or_result.returncode == 0 and gds_path.exists():
                    timing_generated, _, _ = generate_timing_report(module_name)

                    if timing_generated:
                        print(f"[{module_name}] Timing report generated")
                    else:
                        print(f"[{module_name}] Timing report FAILED")
                    copy_openroad_results(problem_stem, module_name)
                    copied_gds = GEN_DIR / problem_stem / "openroad" / f"{module_name}.gds"
                    save_text(
                        status_file,
                        f"PASS\nIterations: {iteration}\nExpected: {expected_text}\nActual  : {actual_text}\n"
                        f"POST_SYNTH: PASS\n"
                        f"OpenROAD: PASS\n"
                        f"GDS (original): {gds_path}\n"
                        f"GDS (copied): {copied_gds}\n"
                    )
                    summary.append(f"{problem_stem}: PASS in {iteration} iteration(s)")
                    print("OpenROAD PASS, GDS generated")
                  
                else:
                    save_text(
                        status_file,
                        f"PASS\nIterations: {iteration}\nExpected: {expected_text}\nActual  : {actual_text}\n"
                        f"POST_SYNTH: PASS\n"
                        f"OpenROAD: FAIL\n{or_result.stderr}\n"
                    )
                    print("OpenROAD FAIL")

                passed = True
                break

            print("FAIL\n")
            rtl_feedback = build_rtl_feedback_prompt(
                module_name,
                module_data,
                expected_text,
                actual_text,
            )
            save_text(rtl_feedback_file, rtl_feedback)
            current_rtl_prompt_file = rtl_feedback_file
            rtl_needs_gen = True
            save_text(
                status_file,
                f"FAIL\nIteration: {iteration}\nExpected: {expected_text}\nActual  : {actual_text}\n"
            )
            continue

        print("PASS (No oracle, sanity check passed)\n")
        save_text(
            status_file,
            f"COMPILE_ONLY\nIterations: {iteration}\nReason: unknown problem compiled and simulated, but no correctness oracle exists.\n"
        )
        summary.append(f"{problem_stem}: PASS (no oracle)")
        passed = True
        break

    if not passed and not any(problem_stem in s for s in summary):
        summary.append(f"{problem_stem}: FAIL after {MAX_ITERS} iteration(s)")

summary_file = LOGS_DIR / "summary.txt"
save_text(summary_file, "\n".join(summary) + "\n")

print("\n==== FINAL SUMMARY ====\n")
for line in summary:
    print(line)
print(f"\nSaved summary to: {summary_file}")
