import sys
import subprocess
import multiprocessing
import random
import functools
import itertools
import io
import os
import re
from pathlib import PosixPath
from enum import Enum
from typing import List, Dict, Set, FrozenSet, Tuple, Callable, Optional
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(it, **kwargs): return it

from config import *

def parse_trace_file(trace_file: io.TextIOWrapper) -> Dict[int, int]:
    result: Dict[int, int] = {}
    for line in trace_file.readlines():
        parts = line.strip().split(":")
        if len(parts) != 1:
            result[parts[0]] = parts[1]
    return result

def get_trace_length(trace_file: io.TextIOWrapper) -> int:
    return sum(c for e, c in parse_trace_file(trace_file).items())


def get_trace_edge_set(trace_file: io.TextIOWrapper) -> FrozenSet[int]:
    return frozenset(e for e, c in parse_trace_file(trace_file).items())


def get_trace_filename(executable: PosixPath, input_file: PosixPath) -> PosixPath:
    return TRACE_DIR.joinpath(PosixPath(f"{input_file.name}.{executable.name}.trace"))

AFLPLUSPLUS_SHOWMAP_STDOUT_FOOTER: bytes = b"\x1b[0;36mafl-showmap"

def normalize_showmap_output(proc: subprocess.Popen, target_config: TargetConfig) -> bytes:
    if proc.stdout is None:
        return b""
    stdout_bytes = proc.stdout.read()
    if USES_AFLPLUSPLUS:
        return stdout_bytes[: stdout_bytes.index(AFLPLUSPLUS_SHOWMAP_STDOUT_FOOTER)]
    else:
        return stdout_bytes

def make_command_line(target_config: TargetConfig, current_input: PosixPath) -> List[str]:
    command_line: List[str] = []
    if target_config.needs_python_afl:
        command_line.append("py-afl-showmap")
    else:
        command_line.append("afl-showmap")
    if target_config.needs_qemu:  # Enable QEMU mode, if necessary
        command_line.append("-Q")
    command_line.append("-e")  # Only care about edge coverage; ignore hit counts
    command_line += [
        "-o",
        str(get_trace_filename(target_config.executable, current_input).resolve()),
    ]
    command_line += ["-t", str(TIMEOUT_TIME)]
    command_line.append("--")
    if target_config.needs_python_afl:
        command_line.append("python3")
    command_line.append(str(target_config.executable.resolve()))
    command_line += target_config.cli_args

    return command_line

def run_executables(
    current_input: PosixPath,
) -> Tuple[Tuple[FrozenSet, ...], Tuple[int, ...], Tuple[bytes, ...]]:
    traced_procs: List[subprocess.Popen] = []

    # We need these to extract exit statuses
    untraced_procs: List[subprocess.Popen] = []

    for target_config in TARGET_CONFIGS:
        command_line: List[str] = make_command_line(target_config, current_input)
        if target_config.traced:
            with open(current_input) as input_file:
                traced_procs.append(
                    subprocess.Popen(
                        command_line,
                        stdin=input_file,
                        stdout=subprocess.PIPE if OUTPUT_DIFFERENTIALS_MATTER else subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=target_config.env,
                    )
                )
        with open(current_input) as input_file:
            untraced_procs.append(
                subprocess.Popen(
                    command_line[command_line.index("--") + 1 :],
                    stdin=input_file,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=target_config.env,
                )
            )

    for proc in itertools.chain(traced_procs, untraced_procs):
        proc.wait()

    stdouts: List[bytes] = []
    for proc, target_config in zip(traced_procs, TARGET_CONFIGS):
        stdouts.append(normalize_showmap_output(proc, target_config))

    l = []
    for c in TARGET_CONFIGS:
        if(c.traced):
            with open(get_trace_filename(c.executable, current_input)) as trace_file:
                l.append(get_trace_edge_set(trace_file))

    traces = tuple(l)

    statuses: Tuple[int, ...] = tuple(proc.returncode for proc in untraced_procs) if EXIT_STATUSES_MATTER else tuple(proc.returncode != 0 for proc in untraced_procs)
    return traces, statuses, tuple(stdouts)