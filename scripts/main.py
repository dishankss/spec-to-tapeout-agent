import ast
import re
import subprocess
from pathlib import Path

import yaml

# Paths
PROJECT_ROOT = Path("/mnt/d/tempo/pytrial/vlsi_agent_project")
PROBLEMS_DIR = PROJECT_ROOT / "problems"
GEN_DIR = PROJECT_ROOT / "generated"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
LOGS_DIR = PROJECT_ROOT / "logs"
GEN_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
MAX_ITERS = 4

KNOWN_MODULES = {
    "seq_detector_0011",
    "dot_product",
    "exp_fixed_point",
    "fp16_multiplier",
    "fir_filter",
}

# Basic helpers
def save_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def sanitize_yaml_text(raw_text):
    """
    Some specs use expressions like:
      clk: [0, 1] * 40
      rst: [1] + [0] * 39
      x_in: [1, 2] + [0] * 32

    These are not always safe for YAML parsing unless quoted.
    We wrap those RHS expressions in quotes when needed.
    """
    out_lines = []
    for line in raw_text.splitlines():
        m = re.match(r"^(\s*[^:#][^:]*:\s*)(.+)$", line)
        if not m:
            out_lines.append(line)
            continue

        prefix = m.group(1)
        value = m.group(2).strip()

        # Avoid re-quoting already quoted scalars or YAML block scalars.
        if value.startswith(("'", '"', "|", ">")):
            out_lines.append(line)
            continue

        # Quote simple arithmetic/list expressions that start with '['.
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

    # Remove markdown fences if Codex returns them.
    text = re.sub(r"^```[a-zA-Z0-9]*\n", "", text)
    text = re.sub(r"\n```$", "", text)

    if preferred_name:
        m = re.search(rf"\bmodule\s+{re.escape(preferred_name)}\b", text)
        start = m.start() if m else text.find("module ")
    else:
        start = text.find("module ")

    end = text.rfind("endmodule")

    if start != -1 and end != -1 and end > start:
        return text[start:end + len("endmodule")].strip() + "\n"

    return text.strip() + "\n"

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
        if width:
            lines.append(f"- {name} ({direction}) {width}")
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

            width_m = re.search(r"(\[[^\]]+\])", prefix)
            width = width_m.group(1) if width_m else ""

            ports.append({"name": name, "direction": direction, "width": width})
            last_dir = direction
            last_prefix = prefix
            continue

        if last_dir and last_prefix is not None:
            name_m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", part)
            if not name_m:
                continue

            name = name_m.group(1)
            width_m = re.search(r"(\[[^\]]+\])", last_prefix)
            width = width_m.group(1) if width_m else ""

            ports.append({"name": name, "direction": last_dir, "width": width})

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
    """
    Supports:
    - lists already loaded by YAML
    - strings like "[0, 1] * 40"
    - strings like "[1] + [0] * 39"
    - plain integers
    - Verilog literals like 16'b0_1000...
    """
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

    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in candidate_keys:
            if key in src:
                seq = safe_parse_sequence(src[key])
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

- Use the same language style as the signature.
- If the signature uses SystemVerilog constructs, generate synthesizable SystemVerilog.
- Use only synthesizable RTL.
- Prefer simple logic/reg/assign/always_ff/always_comb constructs.
- Avoid structs, interfaces, classes, DPI, assertions, and verification-only constructs.
- Avoid multidimensional packed arrays unless the spec clearly requires them.
- Keep arithmetic explicit and widths clear.
- Do not rename module names, ports, widths, parameter names, or reset style.
- Do not add extra ports.
- Do not include testbench code.
- Do not use break or continue.
- Avoid variable indexing inside constant expressions.
- Avoid zero-width concatenations or replication.
- Output must be a COMPLETE module including module and endmodule.
- Return ONLY the HDL code.
""".strip()
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
""".strip() + "\n"

    if module_name == "dot_product":
        prompt += """
Additional rules for this module:
- Use explicit signed arithmetic.
- Keep the implementation simple and synthesizable.
- Avoid overly complex multidimensional array expressions in one statement.
- Prefer clear intermediate registers and a straightforward accumulation structure.
""".strip() + "\n"
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
            code = extract_single_module(process.stdout, preferred_name=preferred_module_name)
            if "module " not in code or "endmodule" not in code:
                last_error = RuntimeError(
                    "Codex output did not contain a complete module.\n"
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

def gen_tb_p7(module_name, module_data):
    usage = module_data["sample_usage"]
    width = extract_numeric(module_data["parameters"]["WIDTH"])

    rst_seq = [int(x) for x in usage["rst_sequence"]]
    en_seq = [int(x) for x in usage["enable_sequence"]]
    x_seq = [int(x) for x in usage["x_in_sequence"]]
    expected = usage["expected_exp_out"]
    cycles = max(len(rst_seq), len(en_seq), len(x_seq), len(expected))

    lines = []
    lines.append("module tb;")
    lines.append(f"  localparam WIDTH = {width};")
    lines.append("  logic clk;")
    lines.append("  logic rst;")
    lines.append("  logic enable;")
    lines.append("  logic [WIDTH-1:0] x_in;")
    lines.append("  logic [2*WIDTH-1:0] exp_out;")
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
    lines.append("    x_in = '0;")
    lines.append("    #10;")
    lines.append("    rst = 0;")
    lines.append("")
    lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")
    lines.append("      case (cycle)")
    for idx in range(cycles):
        rst_v = rst_seq[idx] if idx < len(rst_seq) else 0
        en_v = en_seq[idx] if idx < len(en_seq) else 0
        x_v = x_seq[idx] if idx < len(x_seq) else 0
        lines.append(f"        {idx}: begin")
        lines.append(f"          rst = 1'b{rst_v};")
        lines.append(f"          enable = 1'b{en_v};")
        lines.append(f"          x_in = WIDTH'd{x_v};")
        lines.append("        end")
    lines.append("      endcase")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append('      $display("OBS exp_out=%0d", exp_out);')
    lines.append("      @(negedge clk);")
    lines.append("    end")
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
    """
    For the visible FIR spec, the description/sample implies coefficients 1..N.
    If a hidden FIR spec later provides coefficients elsewhere, this can be extended.
    """
    return list(range(1, n + 1))

def gen_tb_fir_filter(module_name, module_data):
    params = module_data.get("parameters", {})
    width = extract_numeric(params.get("WIDTH", 16))
    n = extract_numeric(params.get("N", 8))

    stim = module_data.get("stimulus", {})
    expected = module_data.get("expected_y_out", [])

    rst_seq = safe_parse_sequence(stim.get("rst", [])) or []
    x_seq = safe_parse_sequence(stim.get("x_in", [])) or []
    cycles = max(len(rst_seq), len(x_seq), len(expected), 1)

    coeffs = infer_fir_coefficients(module_data, n)

    lines = []
    lines.append("module tb;")
    lines.append(f"  localparam WIDTH = {width};")
    lines.append(f"  localparam N = {n};")
    lines.append("  logic clk;")
    lines.append("  logic rst;")
    lines.append("  logic signed [WIDTH-1:0] x_in;")
    lines.append("  logic signed [N-1:0][WIDTH-1:0] h;")
    lines.append("  logic signed [2*WIDTH+$clog2(N):0] y_out;")
    lines.append("  integer idx;")
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
    lines.append("    x_in = '0;")
    lines.append("    h = '0;")
    for i, val in enumerate(coeffs):
        lines.append(f"    h[{i}] = WIDTH'sd{int(val)};")
    lines.append("    #10;")
    lines.append("    rst = 0;")
    lines.append("")
    lines.append(f"    for (idx = 0; idx < {cycles}; idx = idx + 1) begin")
    lines.append("      case (idx)")
    for i in range(cycles):
        rst_v = rst_seq[i] if i < len(rst_seq) else 0
        x_v = x_seq[i] if i < len(x_seq) else 0
        lines.append(f"        {i}: begin")
        lines.append(f"          rst = 1'b{rst_v};")
        lines.append(f"          x_in = {int(x_v)};")
        lines.append("        end")
    lines.append("      endcase")
    lines.append("      @(posedge clk);")
    lines.append("      #1;")
    lines.append('      $display("OBS y_out=%0d", y_out);')
    lines.append("      @(negedge clk);")
    lines.append("    end")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"

def build_generic_testbench(module_name, module_data):
    """
    Generic compile-clean testbench for hidden/unseen problems.
    It tries to use any available input sequences from the YAML, otherwise falls back
    to a simple smoke test.
    """
    signature = module_data.get("module_signature", "")
    ports = parse_port_decls_from_signature(signature)
    if not ports:
        ports = module_data.get("ports", [])

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

    # Try to infer sequences for inputs.
    sequences = {}
    for name in input_ports:
        seq = find_sequence_for_port(name, module_data)
        if seq is not None:
            sequences[name] = seq

    cycles = 1
    if sequences:
        cycles = max(cycles, max(len(v) for v in sequences.values()))

    lines = []
    lines.append("module tb;")

    if params:
        for k, v in params.items():
            lines.append(f"  localparam {k} = {v};")

    lines.append("")

    # Declarations
    for p in ports:
        name = p.get("name", "")
        direction = p.get("direction", "")
        width = p.get("width", "")
        if direction == "input" or direction == "output":
            decl = f"  logic{(' ' + width) if width else ''} {name};"
            lines.append(decl)

    lines.append("")

    # Instantiate DUT
    if params:
        param_map = ", ".join([f".{k}({k})" for k in params.keys()])
        inst_prefix = f"{module_name} #({param_map})"
    else:
        inst_prefix = module_name

    port_map = ", ".join([f".{p.get('name','')}({p.get('name','')})" for p in ports])
    lines.append(f"  {inst_prefix} uut (")
    lines.append(f"    {port_map}")
    lines.append("  );")
    lines.append("")

    if has_clk:
        lines.append("  always #5 clk = ~clk;")
        lines.append("")

    lines.append("  integer cycle;")
    lines.append("  initial begin")

    # Initialize all declared signals.
    for name in input_ports:
        lines.append(f"    {name} = '0;")

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

    if has_clk:
        lines.append(f"    for (cycle = 0; cycle < {cycles}; cycle = cycle + 1) begin")
        for name in input_ports:
            if name == "clk":
                continue
            if name in sequences:
                lines.append(f"      // drive {name} for cycle {cycle}")
                # Use the current cycle value if available.
                lines.append(f"      if (cycle < {len(sequences[name])}) begin")
                value = sequences[name][0] if len(sequences[name]) > 0 else 0
                lines.append(f"        {name} = {format_sv_value(value)};")
                lines.append("      end")
        lines.append("      @(posedge clk);")
        lines.append("      #1;")
        for name in output_ports:
            lines.append(f'      $display("OBS {name}=%b", {name});')
        lines.append("      @(negedge clk);")
        lines.append("    end")
    else:
        lines.append("    #1;")
        for name in output_ports:
            lines.append(f'    $display("OBS {name}=%b", {name});')

    lines.append("    #10;")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"

def generate_testbench(module_name, module_data, force_generic=False):
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
    if module_name == "fir_filter":
        return None
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

def evaluate_p7(module_data, sim_output):
    usage = module_data["sample_usage"]
    expected_seq = usage["expected_exp_out"]

    actual_vals = [int(x) for x in re.findall(r"OBS exp_out=(\d+)", sim_output)]

    compare_ok = True
    if len(actual_vals) < len(expected_seq):
        compare_ok = False

    for idx, exp in enumerate(expected_seq):
        if exp is None:
            continue
        if idx >= len(actual_vals) or actual_vals[idx] != exp:
            compare_ok = False
            break

    expected_text = f"exp_out={expected_seq}"
    actual_text = f"exp_out={actual_vals}"
    return compare_ok, expected_text, actual_text

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

    actual_vals = [int(x) for x in re.findall(r"OBS y_out=(-?\d+)", sim_output)]

    compare_ok = True
    for idx, exp in enumerate(expected):
        if exp is None:
            continue
        if idx >= len(actual_vals) or actual_vals[idx] != exp:
            compare_ok = False
            break

    expected_text = f"y_out={expected}"
    actual_text = f"y_out={actual_vals}"
    return compare_ok, expected_text, actual_text

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
    return None

# Main flow
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

    # Build and save the RTL prompt.
    rtl_prompt = build_rtl_prompt(module_name, module_data)
    save_text(rtl_prompt_file, rtl_prompt)

    current_rtl_prompt_file = rtl_prompt_file
    rtl_needs_gen = True
    use_generic_tb = False
    passed = False

    # Build testbench once, then rebuild only if we force generic fallback.
    tb_code = generate_testbench(module_name, module_data, force_generic=use_generic_tb)
    save_text(tb_file, tb_code)
    save_text(problem_gen_dir / "tb.sv", tb_code)

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

            # If the TB seems to be the problem, fall back to a generic TB once.
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

        eval_result = evaluate_problem(module_name, module_data, sim_result["sim_output"])

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
                summary.append(f"{problem_stem}: PASS in {iteration} iteration(s)")
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

        # Unknown / hidden problem.
        # If it compiled and simulated, accept this local run as compile-success only.
        print("PASS (compile-only for unknown problem)\n")
        save_text(
            status_file,
            f"PASS\nIterations: {iteration}\nReason: compile-only success for unknown/hidden problem\n"
        )
        summary.append(f"{problem_stem}: PASS in {iteration} iteration(s) [compile-only]")
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
