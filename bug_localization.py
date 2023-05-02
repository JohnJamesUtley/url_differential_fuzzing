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
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(it, **kwargs): return it

bugprint_t = int
differenceprint_t = int

TREE_FILENAME = "tree.txt"
MIN_DIR = "min/"
TEST_INPUT = "test.input"

def _find_mins() -> dict[PosixPath, dict[str, frozenset[int]]]:
    target_min_traces = {}
    for target in TARGET_CONFIGS:
        trace_dictionary = {}
        target_min_traces[target.executable] = trace_dictionary
        target_min_traces[target.executable][""] = frozenset()
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
    return target_min_traces

def _classify_by_mins(target_min_traces: dict[PosixPath, dict[str, frozenset[int]]], traces: tuple[frozenset[int], ...]) -> tuple[str, ...]:
    classifications = []
    for trace, target_posix in zip(traces, target_min_traces.keys()):
        min_classification = ""
        for min_trace_id in target_min_traces[target_posix].keys():
            if frozenset.issubset(target_min_traces[target_posix][min_trace_id], trace):
                if set.issubset(set(min_classification), set(min_trace_id)):
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
    for bugprint_dir in os.listdir("bugs"):
        path_bugprint_dir = f"bugs/{bugprint_dir}"
        for input_file in os.listdir(path_bugprint_dir):
            os.remove(f"{path_bugprint_dir}/{input_file}")
        os.rmdir(path_bugprint_dir)

def record_bugprint(input_file: PosixPath, bugprint: bugprint_t):
    dir_name = f"bugs/{bugprint}"
    if not os.path.isdir(dir_name):
        os.makedirs(dir_name)
    shutil.copy2(input_file, f"{dir_name}/")

def get_bugprint(traces: tuple[frozenset], target_min_traces: dict[PosixPath, dict[str, frozenset[int]]]) -> bugprint_t:
    classifications = _classify_by_mins(target_min_traces, traces)
    print(classifications)
    all_diffs = _get_differences_with_bases(classifications, target_min_traces, traces)
    print(all_diffs)
    return hash(all_diffs)

def get_fundamental_traces():
    print("Building Fundamental Traces...")
    gen_tree(TREE_FILENAME)
    fundamental_traces = _find_mins()
    print("Finished Fundamental Traces")
    return fundamental_traces
    
def main():
    # Preprocessing
    fundamental_traces = get_fundamental_traces()
    # Runtime
    print("Running...")
    traces_statuses_stdouts = run_executables(PosixPath(TEST_INPUT))
    print("Finding Diff...")
    bugprint = get_bugprint(traces_statuses_stdouts[0], fundamental_traces)
    print(f"Bug: {bugprint}")

if __name__ == "__main__":
    main()