# Spec-to-Tapeout AI Agent (Final)

## Overview

This project implements an AI-based agent that automates the full Spec-to-Tapeout flow for digital hardware design.

The system takes YAML-based hardware specifications, generates synthesizable RTL using an LLM (Codex CLI), verifies functionality using simulation (Icarus Verilog), performs synthesis and physical design using OpenROAD, and validates correctness again using post-synthesis simulation.

The entire pipeline is automated and iterative, meaning the agent can detect errors and fix them without manual intervention.

---

## Setup Instructions (Dependencies & Environment)

Run the following commands in Ubuntu / WSL:

```bash
sudo apt update
sudo apt install python3-yaml iverilog nodejs npm
sudo npm install -g @openai/codex
```

Then run:

```bash
codex
```

Sign in using your ChatGPT account or API key.

---

### OpenROAD Setup

Clone OpenROAD-flow-scripts:

```bash
git clone https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts
```

Make sure Docker is installed and working.

---

## Important Path Configuration

Before running, update the following paths in:

`scripts/main.py`

```python
PROJECT_ROOT = Path("/your/path/to/project")
OPENROAD_FLOW_ROOT = Path.home() / "OpenROAD-flow-scripts" / "flow"
```

---

## Running on a Different Machine (Path & Environment Setup)

If you want to run this project on another system, follow these steps:

### 1. Update Paths

Edit `scripts/main.py`:

```python
PROJECT_ROOT = Path("/your/path/to/project")
OPENROAD_FLOW_ROOT = Path("/your/path/to/OpenROAD-flow-scripts/flow")
```
---

### 2. Verify Tools

Make sure the following tools are installed:

```bash
python3
iverilog
vvp
codex
docker
```

Check installation:

```bash
iverilog -v
vvp -V
codex
docker --version
```

---

### 3. OpenROAD Location

Ensure OpenROAD exists at:

```
~/OpenROAD-flow-scripts/flow
```

Otherwise update `OPENROAD_FLOW_ROOT`.

---

### 4. Fix Docker Permissions

```bash
sudo usermod -aG docker $USER
```

Restart terminal afterward.

---

### 5. Clean Previous Runs (Optional)

```bash
rm -rf generated/*
rm -rf logs/*
```

---

### 6. Run from Correct Directory

```bash
cd scripts
python3 main.py
```

---
### 7. Visible Testbench Setup (Important)

For visible problems, the system uses official testbenches instead of generated ones.

You must:

* Create a folder in the project root:

```
visible_tb/
```

* Place all official testbench files inside this folder.

Example:

```
visible_tb/
├── iclad_seq_detector_tb.v
├── iclad_dot_product_tb.v
├── iclad_exp_tb.v
├── iclad_fp16_mult_tb.v
├── iclad_fir_tb.v
```

* Ensure the filenames match the mapping defined in `main.py`:

```python
VISIBLE_TB_MAP = {
    "p1": "iclad_seq_detector_tb.v",
    "p5": "iclad_dot_product_tb.v",
    "p7": "iclad_exp_tb.v",
    "p8": "iclad_fp16_mult_tb.v",
    "p9": "iclad_fir_tb.v"
}
```

If your filenames are different, update this mapping accordingly.

---

Without this setup, visible problems will not run correctly.

## How to Run the System

Run a single problem:

```bash
cd scripts
python3 main.py p1.yaml
```

Run all problems:

```bash
cd scripts
python3 main.py
```

---

## Input Description

Input YAML specifications are located in:

```
problems/
```

Each YAML file contains:

* module name
* ports and parameters
* functional description
* sample inputs
* expected outputs

---

## Output Description

Outputs are generated automatically in:

* `generated/` → RTL, testbench, OpenROAD results
* `logs/` → simulation logs and summary
* `prompts/` → LLM prompts and feedback

Each problem folder contains:

* `design.sv` → final RTL
* `tb.sv` → testbench
* `openroad/` → synthesis + layout results
* `timing.rpt` → timing report
* `*.gds` → final layout

---

## Workflow Description

```
YAML Spec
   ↓
RTL Generation (LLM)
   ↓
Simulation (iverilog)
   ↓
Evaluation
   ↓ (if fail → feedback loop)
Synthesis (OpenROAD)
   ↓
Post-Synthesis Simulation
   ↓ (if fail → feedback loop)
Place & Route
   ↓
GDS Output
```

---

## Detailed Steps

1. Parse YAML specification
2. Generate prompt for LLM
3. Generate RTL using Codex CLI
4. Use official testbench (visible problems) or generated testbench
5. Compile using iverilog
6. Run simulation using vvp
7. Compare output with expected results
8. If FAIL → generate feedback → regenerate RTL
9. If PASS → run OpenROAD synthesis
10. Run post-synthesis simulation
11. If PASS → run full PnR flow
12. Generate GDS and timing report

---

## Expected Results

All visible problems pass both:

* Pre-synthesis simulation
* Post-synthesis simulation
* OpenROAD flow

Example:

Problem | Result
p1      | PASS
p5      | PASS
p7      | PASS
p8      | PASS
p9      | PASS

---

## Execution Requirements

* Single command execution
* Fully automated pipeline
* No manual intervention required
* Reproducible results

---

## Notes

* Official testbenches are used for visible problems
* Generated testbenches are used for hidden problems
* Post-synthesis simulation ensures correctness after synthesis
* OpenROAD is used for physical design and GDS generation

---

## Summary

This project demonstrates an AI-driven hardware design system that:

* generates RTL from specifications
* verifies functionality automatically
* fixes errors using feedback loops
* performs synthesis and layout
* validates correctness after synthesis

This completes the full Spec-to-Tapeout pipeline using an AI-based agent.
