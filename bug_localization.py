import sys
import subprocess
import multiprocessing
import shutil
import random
import functools
import itertools
import io
import os
import re
from execution import run_executables
from tree_gen import gen_tree
from config import *
from typing import List, Dict, Set, FrozenSet, Tuple, Callable, Optional
from grammar import grammar_re, grammar_dict, grammar_reductions # type: ignore
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(it, **kwargs): return it

bugprint_t = int
differenceprint_t = int
resultprint_t = int

TREE_FILENAME = "tree.txt"
REDUCTION_FILENAME = "reduction.input"
MIN_DIR = "min/"
TEST_INPUT = "test.input"
BUG_SUMMARY = "bugs_summary.txt"

def _find_mins() -> dict[PosixPath, dict[str, frozenset[int]]]:
    target_min_traces = {}
    for target in TARGET_CONFIGS:
        trace_dictionary = {}
        target_min_traces[target.executable] = trace_dictionary
    min_queue = []
    ids = []
    with open(TREE_FILENAME, "r") as tree_file:
        lines = tree_file.readlines()
        for line in lines:
            id, _, url = line.strip().partition('=')
            min_filename: PosixPath = PosixPath(f"{MIN_DIR}{id}.input")
            with open(f"{MIN_DIR}{id}.input", "w") as min_file:
                 min_file.write(url)
                 min_queue.append(min_filename)
                 ids.append(id)
    with multiprocessing.Pool(processes=multiprocessing.cpu_count() // (len(TARGET_CONFIGS) * 2)) as pool:
        traces_and_statuses_and_stdouts = tqdm(pool.imap(run_executables, min_queue), desc="Running targets", total=len(min_queue))
        for id, (traces, statuses, stdouts) in zip(ids, traces_and_statuses_and_stdouts):
            for target, trace in zip(TARGET_CONFIGS, traces):
                target_min_traces[target.executable][id] = trace
    for target in TARGET_CONFIGS:
        target_min_traces[target.executable][""] = frozenset()
    return target_min_traces

def _classify_by_mins(target_min_traces: dict[PosixPath, dict[str, frozenset[int]]], traces: tuple[frozenset[int], ...]) -> tuple[str, ...]:
    classifications = []
    for trace, target_posix in zip(traces, target_min_traces.keys()):
        min_classification = ""
        curr_classification_dist = len(trace)
        for min_trace_id in target_min_traces[target_posix].keys():
            distance = len(target_min_traces[target_posix][min_trace_id] - trace) + len(trace - target_min_traces[target_posix][min_trace_id])
            # if frozenset.issubset(target_min_traces[target_posix][min_trace_id], trace):
            if distance < curr_classification_dist:
                curr_classification_dist = distance
                # if set.issubset(set(min_classification), set(min_trace_id)):
                min_classification = min_trace_id
                # Check Ordering
                # elif not set.issubset(set(min_trace_id), set(min_classification)):
                #     print("Trace fits into disconnected traces! This is bad.")
        classifications.append(min_classification)
    return tuple(classifications)

def _get_differences_with_bases(classifications: tuple[str, ...],
                               target_min_traces: dict[PosixPath, dict[str, frozenset[int]]],
                               traces: tuple[frozenset[int], ...]) -> tuple[tuple[differenceprint_t], ...]:
    all_trace_differences = []
    for trace, trace_target_posix in zip(traces, target_min_traces.keys()):
        current_trace_differences = []
        for classification, classification_target_posix in zip(classifications, target_min_traces.keys()):
            if trace_target_posix == classification_target_posix:
                current_trace_differences.append(0)
            else:
                current_trace_differences.append(hash(target_min_traces[trace_target_posix][classification] - trace))
        all_trace_differences.append(tuple(current_trace_differences))
    return tuple(all_trace_differences)

def clear_bugprint_records():
    if os.path.isfile(f"bugs/{BUG_SUMMARY}"):
        os.remove(f"bugs/{BUG_SUMMARY}")
    for bugprint_dir in os.listdir("bugs"):
        path_bugprint_dir = f"bugs/{bugprint_dir}"
        for input_file in os.listdir(path_bugprint_dir):
            os.remove(f"{path_bugprint_dir}/{input_file}")
        os.rmdir(path_bugprint_dir)

bugprint_counter: dict[str, int] = {}
bug_reductions: dict[bugprint_t, set[bytes]] = {}

def record_bugprint(input_file: PosixPath, bugprint: bugprint_t):
    if bugprint in bugprint_counter.keys():
        bugprint_counter[bugprint] = bugprint_counter[bugprint] + 1
    else:
        bugprint_counter[bugprint] = 1
    dir_name = f"bugs/{bugprint}"
    if not os.path.isdir(dir_name):
        os.makedirs(dir_name)
    shutil.copy2(input_file, f"{dir_name}/")

def bugprint_summary():
    with open(PosixPath(f"bugs/{BUG_SUMMARY}"), "wb") as summary_file:
        summary_file.write(b"Exit Statuses Matter: " + (b"TRUE" if EXIT_STATUSES_MATTER else b"FALSE") + b"\n")
        summary_file.write(b"Output Differentials Matter: " + (b"TRUE" if OUTPUT_DIFFERENTIALS_MATTER else b"FALSE") + b"\n")
        summary_file.write(b"Targets:\n")
        summary_file.write(b"\n".join(bytes(tc.executable) for tc in TARGET_CONFIGS))
        summary_file.write(b"\nBugs:\n")
        print(sorted(bugprint_counter.items(), key=lambda x:x[1], reverse=True))
        for bug in sorted(bugprint_counter.items(), key=lambda x:x[1], reverse=True):
            summary_file.write(bytes(str(bug), "utf-8") + b"\n")
            for reduction in bug_reductions[bug[0]]:
                summary_file.write(b"***" + reduction + b"***\n")

def get_bugprint(traces: tuple[frozenset], target_min_traces: dict[PosixPath, dict[str, frozenset[int]]]) -> bugprint_t:
    classifications = _classify_by_mins(target_min_traces, traces)
    all_diffs = _get_differences_with_bases(classifications, target_min_traces, traces)
    bugprint = hash(all_diffs)
    if BUG_INFO:
        print(classifications)
        print(all_diffs)
    return bugprint

def get_reduction_bugprint(input: bytes, base_resultprint: resultprint_t) -> bugprint_t:
    reduced_form = get_reduced_form(input, base_resultprint)
    print(f"Reduced: {reduced_form}")
    reduced_filename: PosixPath = PosixPath(REDUCTION_FILENAME)
    traces_statuses_stdouts = run_executables(reduced_filename)
    traces = traces_statuses_stdouts[0]
    bugprint = hash(traces)
    if BUG_INFO:
        if not os.path.isdir(PosixPath(f"bugs/{bugprint}")):
            os.makedirs(PosixPath(f"bugs/{bugprint}"))
        record_filename: PosixPath = PosixPath(f"bugs/{bugprint}/{hash(input)}.reduction")
        with open(record_filename, "wb") as record_file:
            record_file.write(reduced_form)
        if bugprint not in bug_reductions.keys():
            bug_reductions[bugprint] = {reduced_form}
        else:
            bug_reductions[bugprint].add(reduced_form)
    return bugprint

def get_resultprint(traces_statuses_stdouts: Tuple[Tuple[FrozenSet[int], ...], Tuple[int, ...], Tuple[bytes, ...]]) -> resultprint_t:
    statuses = traces_statuses_stdouts[1]
    if OUTPUT_DIFFERENTIALS_MATTER:
        stdouts = traces_statuses_stdouts[2]
        stdout_set = set()
        for stdout in stdouts:
            stdout_set.add(stdout)
        different_stdouts = (len(stdout_set) == 1)
        return hash((statuses, different_stdouts))
    else: 
        return hash(statuses)
    
def reduce_by_bytes(input_bytes: bytes, num_bytes: int, base_resultprint: resultprint_t) -> bytes:
    reduced_filename: PosixPath = PosixPath(REDUCTION_FILENAME)
    running_reduction = input_bytes

    completely_reduced = False
    while not completely_reduced:
        completely_reduced = True
        i = 0
        while i < len(running_reduction):
            # Get Resultprint
            reduction = running_reduction[:i] + running_reduction[i + num_bytes:]
            with open(reduced_filename, "wb") as reduced_file:
                reduced_file.write(reduction)
            traces_statuses_stdouts = run_executables(reduced_filename)
            resultprint = get_resultprint(traces_statuses_stdouts)            
            # -----------
            if resultprint == base_resultprint: # Save this reduction if results match, else continue on
                running_reduction = reduction
                print(reduction)
                completely_reduced = False
            else:
                i = i + 1
    return running_reduction

def get_reduced_form(input: bytes, base_resultprint: resultprint_t) -> bytes:
    running_reduction = input

    reduced_filename: PosixPath = PosixPath(REDUCTION_FILENAME)

    grammar_reduced = False
    reduced_rules = set()
    while not grammar_reduced:
        m: Optional[re.Match] = re.match(grammar_re, str(running_reduction, "UTF-8"))
        if m is not None:
            grammar_reduced = True
            for rule_name, orig_rule_match in list(filter(lambda p: bool(p[1]), m.groupdict().items())):
                if rule_name not in reduced_rules:
                    # Get Resultprint
                    slice_index: int = m.string.index(orig_rule_match)
                    if GRAMMAR_REDUCTIONS:
                        reduction = bytes(running_reduction[:slice_index] + grammar_reductions[rule_name] + running_reduction[slice_index + len(orig_rule_match):])
                    else:
                        reduction = bytes(running_reduction[:slice_index] + running_reduction[slice_index + len(orig_rule_match):])
                    with open(reduced_filename, "wb") as reduced_file:
                        reduced_file.write(reduction)
                    traces_statuses_stdouts = run_executables(reduced_filename)
                    resultprint = get_resultprint(traces_statuses_stdouts)
                    # -----------
                    if resultprint == base_resultprint: # Save this reduction if results match, else continue on
                        reduced_rules.add(rule_name)
                        running_reduction = reduction
                        grammar_reduced = False
                        break
        else:
            grammar_reduced = True

    for i in range(MAX_BYTES_REDUCTION, 0, -1):
        running_reduction = reduce_by_bytes(running_reduction, i, base_resultprint)

    return running_reduction

def get_fundamental_traces():
    print("Building Fundamental Traces...")
    gen_tree(TREE_FILENAME)
    fundamental_traces = _find_mins()
    print("Finished Fundamental Traces")
    return fundamental_traces
    
def main():
    # Preprocessing
    # fundamental_traces = get_fundamental_traces()
    # Runtime
    print("Running...")
    traces_statuses_stdouts = run_executables(PosixPath(TEST_INPUT))
    base_resultprint = get_resultprint(traces_statuses_stdouts)
    with open(PosixPath(TEST_INPUT), "rb") as input_file:
        read_input: bytes = input_file.read()
    print("Finding Diff...")
    reduction_bugprint = get_reduction_bugprint(read_input, base_resultprint)
    print(f"Bug: {reduction_bugprint}")



if __name__ == "__main__":
    main()