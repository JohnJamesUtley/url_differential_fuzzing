#############################################################################################
# diff_fuzz.py
# This is a wrapper around afl-showmap that does differential fuzzing a la
#   https://github.com/nezha-dt/nezha, but much slower.
# Fuzzing targets are configured in `py`.
#############################################################################################

import sys
import subprocess
import multiprocessing
import random
import uuid
import functools
import itertools
import os
import re
import json
import shutil
from dataclasses import fields
from pathlib import PosixPath
from typing import List, Set, FrozenSet, Tuple, Callable, Any

try:
    from tqdm import tqdm  # type: ignore
except ModuleNotFoundError:
    tqdm = lambda it, **kwargs: it  # type: ignore

from config import (
    ParseTree,
    compare_parse_trees,
    TargetConfig,
    TIMEOUT_TIME,
    TARGET_CONFIGS,
    ROUGH_DESIRED_QUEUE_LEN,
    SEED_DIR,
    DETECT_OUTPUT_DIFFERENTIALS,
    DIFFERENTIATE_NONZERO_EXIT_STATUSES,
    DELETION_LENGTHS,
    RESULTS_DIR,
    USE_GRAMMAR_MUTATIONS,
    EXECUTION_DIR
)

if USE_GRAMMAR_MUTATIONS:
    try:
        from grammar import generate_random_matching_input, grammar_re, grammar_dict  # type: ignore
    except ModuleNotFoundError:
        print(
            "`grammar.py` not found. Either make one or set USE_GRAMMAR_MUTATIONS to False", file=sys.stderr
        )
        sys.exit(1)

assert SEED_DIR.is_dir()
SEED_INPUTS: List[PosixPath] = list(map(lambda s: SEED_DIR.joinpath(PosixPath(s)), os.listdir(SEED_DIR)))

assert RESULTS_DIR.is_dir()

assert all(map(lambda tc: tc.executable.exists(), TARGET_CONFIGS))

fingerprint_t = Tuple[FrozenSet[int], ...]


def grammar_mutate(m: re.Match, _: Any) -> bytes:
    # This function takes _ so it can have the same
    # signature as the other mutators after currying with m,
    # even though _ is ignored.
    rule_name, orig_rule_match = random.choice(list(filter(lambda p: bool(p[1]), m.groupdict().items())))
    new_rule_match: str = generate_random_matching_input(grammar_dict[rule_name])

    # This has a chance of being wrong, but that's okay in my opinion
    slice_index: int = m.string.index(orig_rule_match)

    return bytes(
        m.string[:slice_index] + new_rule_match + m.string[slice_index + len(orig_rule_match) :],
        "UTF-8",
    )


def byte_change(b: bytes) -> bytes:
    index: int = random.randint(0, len(b) - 1)
    return b[:index] + bytes([random.randint(0, 255)]) + b[index + 1 :]


def byte_insert(b: bytes) -> bytes:
    index: int = random.randint(0, len(b))
    return b[:index] + bytes([random.randint(0, 255)]) + b[index:]


def byte_delete(b: bytes) -> bytes:
    index: int = random.randint(0, len(b) - 1)
    return b[:index] + b[index + 1 :]


def mutate(b: bytes) -> bytes:
    mutators: List[Callable[[bytes], bytes]] = [byte_insert]
    if len(b) > 0:
        mutators.append(byte_change)
    if len(b) > 1:
        mutators.append(byte_delete)
    if USE_GRAMMAR_MUTATIONS:
        try:
            m: re.Match | None = re.match(grammar_re, str(b, "UTF-8"))
            if m is not None:
                mutators.append(functools.partial(grammar_mutate, m))
        except UnicodeDecodeError:
            pass

    return random.choice(mutators)(b)


def parse_tracer_output(tracer_output: bytes) -> FrozenSet[int]:
    result: Set[int] = set()
    for line in tracer_output.split(b"\n"):
        try:
            edge, _ = map(int, line.strip().split(b":"))
            result.add(edge)
        except ValueError:
            pass
    return frozenset(result)


def make_command_line(tc: TargetConfig, input_dir: PosixPath | None=None, output_dir: PosixPath | None=None) -> List[str]:
    command_line: List[str] = []
    if tc.needs_tracing and input_dir is not None and output_dir is not None:
        if tc.needs_python_afl:
            command_line.append("py-afl-showmap")
        else:
            command_line.append("afl-showmap")
            if tc.needs_qemu:  # Enable QEMU mode, if necessary
                command_line.append("-Q")
        command_line += ["-i", str(input_dir.resolve())]
        command_line += ["-o", str(output_dir.resolve())]
        command_line.append("-q")  # Don't care about traced program stdout
        command_line.append("-e")  # Only care about edge coverage; ignore hit counts
        command_line += ["-t", str(TIMEOUT_TIME)]
        command_line.append("--")

    if tc.needs_python_afl:
        command_line.append("python3")
    command_line.append(str(tc.executable.resolve()))
    command_line += tc.cli_args

    return command_line


def minimize_differential(bug_inducing_input: bytes) -> bytes:
    orig_outputs = run_executables((bug_inducing_input,), disable_tracing=True)
    _, orig_statuses, orig_parse_trees = orig_outputs[0]
    needs_parse_tree_comparison: bool = len(set(orig_statuses)) == 1
    
    orig_parse_tree_comparisons: List[Tuple[bool, ...]] = (
        list(itertools.starmap(compare_parse_trees, itertools.combinations(orig_parse_trees, 2)))
        if needs_parse_tree_comparison
        else [(True,)]
    )

    result: bytes = bug_inducing_input

    for deletion_length in DELETION_LENGTHS:
        i: int = len(result) - deletion_length
        while i >= 0:
            reduced_form: bytes = result[:i] + result[i + deletion_length :]
            new_outputs = run_executables((reduced_form,), disable_tracing=True)
            _, new_statuses, new_parse_trees = new_outputs[0]
            if (
                new_statuses == orig_statuses
                and (
                    list(itertools.starmap(compare_parse_trees, itertools.combinations(new_parse_trees, 2)))
                    if needs_parse_tree_comparison
                    else [(True,)]
                )
                == orig_parse_tree_comparisons
            ):
                result = reduced_form
                i -= deletion_length
            else:
                i -= 1
    return result

@functools.lru_cache
def run_executables(current_inputs: Tuple[bytes], disable_tracing: bool = False, only_recorded_traces: bool = False) -> List[Tuple[fingerprint_t,Tuple[int, ...],Tuple[ParseTree | None, ...]]]:

    # Create directory to run showmap, save it for later
    exec_dir = EXECUTION_DIR.joinpath(str(uuid.uuid4()))
    gen_dir = exec_dir.joinpath("generation")
    trace_dir = exec_dir.joinpath("trace")

    traced_procs: List[subprocess.Popen | None] = []

    if not disable_tracing:
        # Create sub directories
        os.mkdir(exec_dir)
        os.mkdir(gen_dir)
        os.mkdir(trace_dir)

        # Write the inputs into files
        for current_input, i in zip(current_inputs, range(len(current_inputs))):
            with open(gen_dir.joinpath(str(i)), "wb") as input_file:
                input_file.write(current_input)

        for tc, i in zip(TARGET_CONFIGS, range(len(TARGET_CONFIGS))):
            # Create an output folder
            output_dir = trace_dir.joinpath(str(i))
            os.mkdir(output_dir)
            command_line: List[str] = make_command_line(tc, gen_dir, output_dir)
            if tc.needs_tracing:
                traced_proc: subprocess.Popen = subprocess.Popen(
                    command_line,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=tc.env,
                )
                traced_procs.append(traced_proc)
            else:
                traced_procs.append(None)

    # We need these to extract exit statuses and parse_trees
    untraced_procs: List[subprocess.Popen | None] = []
    for current_input in current_inputs:
        for tc in TARGET_CONFIGS:
            if tc.record_differentials:
                untraced_command_line: List[str] = make_command_line(tc, None, None)
                untraced_proc: subprocess.Popen = subprocess.Popen(
                    untraced_command_line,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE if DETECT_OUTPUT_DIFFERENTIALS else subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=tc.env,
                )
                assert untraced_proc.stdin is not None
                untraced_proc.stdin.write(current_input)
                untraced_proc.stdin.close()
                untraced_procs.append(untraced_proc)
            else:
                untraced_procs.append(None)

    # Wait for the processes to exit
    for proc in itertools.chain(untraced_procs, traced_procs):
        if proc is not None:
            proc.wait()

    all_results: List[Tuple[fingerprint_t,Tuple[int, ...],Tuple[ParseTree | None, ...]]] = []

    process_counter: int = 0
    for file_counter in range(len(current_inputs)):
        statuses: List[int] = []
        parse_trees: List[ParseTree | None] = []
        traces: List[FrozenSet[int]] = []
        for tc, target_num in zip(TARGET_CONFIGS, range(len(TARGET_CONFIGS))):
            proc = untraced_procs[process_counter]
            process_counter += 1
            # Recover statuses and parse trees
            if tc.record_differentials:
                status = proc.returncode if DIFFERENTIATE_NONZERO_EXIT_STATUSES else int(proc.returncode)
                statuses.append(status)
                parse_trees.append(
                    ParseTree(**{k: v for k, v in json.loads(proc.stdout.read()).items()})
                    if proc.stdout is not None and status == 0
                    else None
                )
            # Recover fingerprint
            if not disable_tracing:
                # Recover fingerprint
                output_filename = trace_dir.joinpath(str(target_num)).joinpath(str(file_counter))
                if os.path.isfile(output_filename) and (tc.record_differentials == True or not only_recorded_traces):
                    with open(output_filename, "rb") as trace_file:
                        traces.append(parse_tracer_output(trace_file.read()))
                else:  # Empty Input results in no file
                    traces.append(frozenset())

        all_results.append((tuple(traces), tuple(statuses), tuple(parse_trees)))

    if not disable_tracing:
        shutil.rmtree(exec_dir)

    return all_results


def main(minimized_differentials: List[bytes]) -> None:
    # We take minimized_differentials as an argument because we want
    # it to persist even if this function has an uncaught exception.
    assert len(minimized_differentials) == 0

    # Clear out the execution directory
    if os.path.exists(EXECUTION_DIR):
        shutil.rmtree(EXECUTION_DIR)

    os.mkdir(EXECUTION_DIR)

    input_queue: List[bytes] = []
    for seed_input in SEED_INPUTS:
        with open(seed_input, "rb") as f:
            input_queue.append(f.read())

    # One input `I` produces one trace per program being fuzzed.
    # Convert each trace to a (frozen)set of edges by deduplication.
    # Pack those sets together in a tuple (and maybe hash it).
    # This is a fingerprint of the programs' execution on the input `I`.
    # Keep these fingerprints in a set.
    # An input is worth mutation if its fingerprint is new.
    seen_fingerprints: Set[fingerprint_t] = set()

    # This is the set of fingerprints that correspond with minimized differentials.
    # Whenever we minimize a differential into an input with a fingerprint not in this set,
    # we report it and add it to this set.
    minimized_fingerprints: Set[fingerprint_t] = set()

    generation: int = 0

    while len(input_queue) != 0:  # While there are still inputs to check,
        print(f"Starting generation {generation}.", file=sys.stderr)
        mutation_candidates: List[bytes] = []
        differentials: List[bytes] = []

        # run the programs on the things in the input queue.
        input_queue_pos: int = 0
        batches: List[Tuple[bytes, ...]] = []
        num_cpus: int|None = os.cpu_count()
        assert num_cpus is not None
        for cpu in range(num_cpus):
            batch: List[bytes] = []
            for _ in range(len(input_queue) // num_cpus + 1):
                if input_queue_pos >= len(input_queue):
                    break
                batch.append(input_queue[input_queue_pos])
                input_queue_pos += 1
            batches.append(tuple(batch))
            
        with multiprocessing.Pool(os.cpu_count()) as pool:

            batch_executions = tqdm(
                pool.imap(run_executables, batches),
                desc="Running Targets",
                total=len(differentials),
            )

            all_outputs: List[Tuple[fingerprint_t,Tuple[int, ...],Tuple[ParseTree | None, ...]]] = []
            for executions in batch_executions:
                all_outputs.extend(executions)

        for current_input, (fingerprint, statuses, parse_trees) in zip(
            input_queue, all_outputs
        ):
            # If we found something new, mutate it and add its children to the input queue
            # If we get one program to fail while another succeeds, then we're doing good.
            if fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                status_set: Set[int] = set(statuses)
                if (len(status_set) != 1) or (
                    DETECT_OUTPUT_DIFFERENTIALS and status_set == {0} and len(set(parse_trees)) != 1
                ):
                    differentials.append(current_input)
                else:
                    mutation_candidates.append(current_input)

        with multiprocessing.Pool(os.cpu_count()) as pool:

            minimized_inputs_tqdm = tqdm(
                pool.imap(minimize_differential, differentials),
                desc="Minimizing Differentials",
                total=len(differentials),
            )

            minimized_inputs = tuple(minimized_inputs_tqdm)

        # TODO: Multiprocess this?
        minimized_outputs = run_executables(minimized_inputs, only_recorded_traces=True)

        for (minimized_fingerprint, _, _), minimized_input in zip(
            minimized_outputs, minimized_inputs
        ):
            if minimized_fingerprint not in minimized_fingerprints:
                minimized_differentials.append(minimized_input)
                minimized_fingerprints.add(minimized_fingerprint)

        input_queue.clear()
        while len(mutation_candidates) != 0 and len(input_queue) < ROUGH_DESIRED_QUEUE_LEN:
            input_queue += list(map(mutate, mutation_candidates))

        print(
            f"End of generation {generation}.\n"
            + f"Differentials:\t\t{len(minimized_differentials)}\n"
            + f"Mutation candidates:\t{len(mutation_candidates)}",
            file=sys.stderr,
        )
        generation += 1


if __name__ == "__main__":
    if len(sys.argv) > 2:
        print(f"Usage: python3 {sys.argv[0]}", file=sys.stderr)
        sys.exit(1)

    final_results: List[bytes] = []
    try:
        main(final_results)
    except KeyboardInterrupt:
        pass

    # Clean up interrupted files
    shutil.rmtree(EXECUTION_DIR)

    if len(final_results) != 0:
        print("Differentials:", file=sys.stderr)
        print("\n".join(repr(b) for b in final_results))
    else:
        print("No differentials found! Try increasing ROUGH_DESIRED_QUEUE_LEN.", file=sys.stderr)

    run_id: str = str(uuid.uuid4())
    os.mkdir(RESULTS_DIR.joinpath(run_id))
    for ctr, final_result in enumerate(final_results):
        with open(RESULTS_DIR.joinpath(run_id).joinpath(f"differential_{ctr}"), "wb") as result_file:
            result_file.write(final_result)
