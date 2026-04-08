# spec-to-tapeout-agent
AI-based Spec-to-Tapeout automation using LLM + simulation loop

# Spec-to-Tapeout AI Agent (Phase 2)

## Overview

This project implements an AI-based agent that automates RTL generation and verification from hardware specifications.
The system takes YAML-based hardware specifications, generates RTL using Codex CLI, verifies functionality using simulation (Icarus Verilog), and iteratively improves the design using feedback.
The workflow is fully automated and reproducible.

## Setup Instructions (Dependencies & Environment)

Run the following commands in Ubuntu / WSL:

```bash
sudo apt update
sudo apt install python3-yaml iverilog nodejs npm
sudo npm install -g @openai/codex
```

After installation, run:

```bash
codex
```
#After installation, run:

codex

and sign in using your ChatGPT account or API key.

## How to Run the System (Single Command)

```bash
cd scripts
python3 main.py
```


## Input Description

Input files are YAML specifications located in:

problems/

Each YAML file contains:
- module name
- ports and parameters
- functional description
- sample inputs
- expected outputs

## Output Description

Outputs are generated automatically in the following folders:

- generated/ → generated RTL and testbench files  
- logs/ → simulation logs and summary results  
- prompts/ → LLM prompts and feedback prompts  

## Expected Results (Verification)

Example results from the current system:

Problem | Result | Iterations  
p1      | PASS   | 2–4  
p5      | PASS   | 2–3  
p8      | PASS   | 1  
p7      | FAIL   | -  
p9      | FAIL   | -  

PASS indicates simulation output matches expected behavior.

## Workflow Description

The system follows this automated loop:

YAML → Prompt → Codex → RTL → Simulation → Compare → Feedback → Retry

Detailed steps:

1. Parse YAML specification  
2. Generate structured prompt for LLM  
3. Generate RTL using Codex CLI  
4. Generate testbench automatically  
5. Compile using iverilog  
6. Run simulation using vvp  
7. Extract output values  
8. Compare with expected results  
9. If FAIL → generate feedback → retry  

## Running Hidden Testcases

```bash
cd scripts
python3 main.py
```

## Execution Requirement

- Single command to run pipeline:
  cd scripts
  python3 main.py

- Fully automated workflow \
- Reproducible results

## Notes

- Codex CLI is used for RTL generation  
- Icarus Verilog is used for simulation  
- System supports iterative correction using feedback  
- Some complex parameterized or pipelined designs may require further improvement  

## Summary

This project demonstrates an AI-driven hardware design agent that:
- generates RTL from specification  
- verifies correctness using simulation  
- automatically refines designs using feedback  
- supports multiple problem types  
