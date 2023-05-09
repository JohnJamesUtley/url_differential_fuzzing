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
from datetime import datetime
import time
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(it, **kwargs): return it

bugprint_t = int
differenceprint_t = int
resultprint_t = int

LISTED_EXAMPLES_PER_BUG: int = 4

TREE_FILENAME = "tree.txt"
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
bug_stdout_differential: dict[bugprint_t, bool] = {}

def record_bugprint(input_file: PosixPath, bugprint: bugprint_t, stdout_differential: bool):
    if bugprint in bugprint_counter.keys():
        bugprint_counter[bugprint] = bugprint_counter[bugprint] + 1
    else:
        bugprint_counter[bugprint] = 1
    bug_stdout_differential[bugprint] = stdout_differential
    dir_name = f"bugs/{bugprint}"
    if not os.path.isdir(dir_name):
        os.makedirs(dir_name)
    shutil.copy2(input_file, f"{dir_name}/")

def bugprint_summary(fingerprint_count: int, inputs_run: int, generation: int, start_time: float, termination_reason: str):
        print("-----------RUN INFO----------", file=sys.stderr)
        print("\nLAST COMMIT: " + str(subprocess.check_output(["git", "describe", "--always"]).strip()), file=sys.stderr)
        print("\nDATE: " + str(datetime.now().strftime("%d/%m/%Y %H:%M:%S")), file=sys.stderr)
        print("\nTARGETS:")
        for tc in TARGET_CONFIGS:
            print(str(tc.executable), file=sys.stderr)
            print("\tTraced: "+ str(tc.traced), file=sys.stderr)
        print("\nOPTIONS:", file=sys.stderr)
        print("Exit Statuses Matter: " + ("TRUE" if EXIT_STATUSES_MATTER else "FALSE"), file=sys.stderr)
        print("Output Differentials Matter: " + ("TRUE" if OUTPUT_DIFFERENTIALS_MATTER else "FALSE"), file=sys.stderr)
        print("\n-----------RESULTS----------", file=sys.stderr)
        print("\nTERMINATION REASON: " + termination_reason, file=sys.stderr)
        print("\tCPU EXECUTION TIME: " + str(time.process_time()) + " Seconds", file=sys.stderr)
        print("\tACTUAL EXECUTION TIME: " + str(time.time() - start_time) + " Seconds", file=sys.stderr)
        print("\nINPUTS RUN: " + str(inputs_run), file=sys.stderr)
        print("\tFINGERPRINTS EXPLORED: " + str(fingerprint_count), file=sys.stderr)
        print("\tGENERATIONS COMPLETED: " + str(generation), file=sys.stderr)
        print("\nTOTAL BUGS FOUND: " + str(sum(x for x in bugprint_counter.values())), file=sys.stderr)
        print("\tBUGPRINTS FOUND: " + str(len(bugprint_counter.keys())), file=sys.stderr)
        print("\tBUGS WITH UNIQUE BUGPRINTS: " + str(sum(x for x in bugprint_counter.values() if x == 1)), file=sys.stderr)
        print("\nEXIT DIFFERENTIAL BUGS FOUND: " + str(sum(bugprint_counter[x] for x in bugprint_counter.keys() if not bug_stdout_differential[x])), file=sys.stderr)
        print("\tBUGPRINTS FOUND: " + str(sum(1 for x in bugprint_counter.keys() if not bug_stdout_differential[x])), file=sys.stderr)
        print("\tBUGS WITH UNIQUE BUGPRINTS: " + str(sum(bugprint_counter[x] for x in bugprint_counter.keys() if bugprint_counter[x] == 1 and not bug_stdout_differential[x])), file=sys.stderr)
        print("\nSTDOUT DIFFERENTIAL BUGS FOUND: " + str(sum(bugprint_counter[x] for x in bugprint_counter.keys() if bug_stdout_differential[x])), file=sys.stderr)
        print("\tBUGPRINTS FOUND: " + str(sum(1 for x in bugprint_counter.keys() if bug_stdout_differential[x])), file=sys.stderr)
        print("\tBUGS WITH UNIQUE BUGPRINTS: " + str(sum(bugprint_counter[x] for x in bugprint_counter.keys() if bugprint_counter[x] == 1 and bug_stdout_differential[x])), file=sys.stderr)
        print("\nBUGS:", file=sys.stderr)
        for bug in sorted(bugprint_counter.items(), key=lambda x:x[1], reverse=True):
            print(str(bug) + ": " + ("exit differential" if not bug_stdout_differential[bug[0]] else "stdout differential"), file=sys.stderr)
            for reduction in list(bug_reductions[bug[0]])[0:LISTED_EXAMPLES_PER_BUG]:
                print("***" + repr(reduction) + "***", file=sys.stderr)


def get_bugprint(traces: tuple[frozenset], target_min_traces: dict[PosixPath, dict[str, frozenset[int]]]) -> bugprint_t:
    classifications = _classify_by_mins(target_min_traces, traces)
    all_diffs = _get_differences_with_bases(classifications, target_min_traces, traces)
    bugprint = hash(all_diffs)
    if BUG_INFO:
        print(classifications)
        print(all_diffs)
    return bugprint

def get_reduction_bugprint(input: bytes, base_resultprint: resultprint_t, reduced_filename: PosixPath) -> bugprint_t:
    reduced_form = get_reduced_form(input, base_resultprint, reduced_filename)
    # print(f"Reduced: {reduced_form}")
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
    
def reduce_by_bytes(input_bytes: bytes, num_bytes: int, base_resultprint: resultprint_t, reduced_filename: PosixPath) -> bytes:
    running_reduction = input_bytes

    completely_reduced = False
    while not completely_reduced:
        # print(str(running_reduction))
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
                completely_reduced = False
            else:
                i = i + 1
    return running_reduction

def get_reduced_form(input: bytes, base_resultprint: resultprint_t, reduced_filename: PosixPath) -> bytes:
    running_reduction = input

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
        running_reduction = reduce_by_bytes(running_reduction, i, base_resultprint, reduced_filename)

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