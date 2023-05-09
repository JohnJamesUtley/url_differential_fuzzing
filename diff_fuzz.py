#############################################################################################
# diff_fuzz.py
# This is a wrapper around afl-showmap that does differential fuzzing a la
#   https://github.com/nezha-dt/nezha, but much slower.
# Fuzzing targets are configured in `config.py`.
#############################################################################################

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
from execution import run_executables
from bug_localization import *
try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(it, **kwargs): return it

from config import *

HAS_GRAMMAR: bool = False
try:
    from grammar import generate_random_matching_input, grammar_re, grammar_dict # type: ignore

    print("Importing grammar from `grammar.py`.", file=sys.stderr)
    HAS_GRAMMAR = True
except:
    print("`grammar.py` not found; disabling grammar-based mutation.", file=sys.stderr)

SEED_INPUTS: List[PosixPath] = list(map(SEED_DIR.joinpath, map(PosixPath, os.listdir(SEED_DIR))))

for tc in TARGET_CONFIGS:
    assert tc.executable.is_file()
assert TRACE_DIR.is_dir()
assert SEED_DIR.is_dir()
for seed in SEED_INPUTS:
    assert seed.is_file()

fingerprint_t = int


def grammar_mutate(m: re.Match, _: bytes) -> bytes:
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


def mutate_input(input_filename: PosixPath) -> PosixPath:
    mutant_filename: PosixPath = PosixPath(f"inputs/{random.randint(0, 2**32-1)}.input")
    with open(mutant_filename, "wb") as ofile, open(input_filename, "rb") as ifile:
        b: bytes = ifile.read()

        mutators: List[Callable[[bytes], bytes]] = [byte_insert]
        if len(b) > 0:
            mutators.append(byte_change)
        if len(b) > 1:
            mutators.append(byte_delete)
        if HAS_GRAMMAR:
            try:
                m: Optional[re.Match] = re.match(grammar_re, str(b, "UTF-8"))
                if m is not None:
                    mutators.append(functools.partial(grammar_mutate, m))
            except UnicodeDecodeError:
                pass

        ofile.write(random.choice(mutators)(b))

    return mutant_filename

class AutoTerminationException(Exception):
    "Raised to terminate fuzzing at a pre-defined time"
    pass

def main() -> None:
    if len(sys.argv) > 2:
        print(f"Usage: python3 {sys.argv[0]}", file=sys.stderr)
        sys.exit(1)


    clear_bugprint_records()

    input_queue: List[PosixPath] = SEED_INPUTS.copy()

    # One input `I` produces one trace per program being fuzzed.
    # Convert each trace to a (frozen)set of edges by deduplication.
    # Pack those sets together in a tuple and hash it.
    # This is a fingerprint of the programs' execution on the input `I`.
    # Keep these fingerprints in a set.
    # An input is worth mutation if its fingerprint is new.
    explored: Set[fingerprint_t] = set()

    inputs_run: int = 0
    start_time: float = time.time()
    termination_reason: str = "No Reason Found"

    generation: int = 0
    exit_status_differentials: List[PosixPath] = []
    output_differentials: List[PosixPath] = []
    try:
        with multiprocessing.Pool(processes=multiprocessing.cpu_count() // (len(TARGET_CONFIGS) * 2)) as pool:
            while len(input_queue) != 0:  # While there are still inputs to check,
                print(
                    color(
                        Color.green,
                        f"Starting generation {generation}. {len(input_queue)} inputs to try.",
                    )
                )
                # run the programs on the things in the input queue.
                traces_and_statuses_and_stdouts = tqdm(pool.imap(run_executables, input_queue), desc="Running targets", total=len(input_queue))

                mutation_candidates: List[PosixPath] = []
                rejected_candidates: List[PosixPath] = []

                for current_input, (traces, statuses, stdouts) in zip(
                    input_queue, traces_and_statuses_and_stdouts
                ):
                    if AUTO_TERMINATION != -1:
                        if time.time() - start_time > AUTO_TERMINATION:
                            raise AutoTerminationException
                    inputs_run = inputs_run + 1
                    fingerprint = hash(traces)
                    # If we found something new, mutate it and add its children to the input queue
                    # If we get one program to fail while another succeeds, then we're doing good.
                    if fingerprint not in explored:
                        explored.add(fingerprint)
                        if len(set(statuses)) != 1 or len(set(stdouts)) != 1:
                            with open(current_input, "rb") as iFile:
                                current_input_bytes: bytes = iFile.read()
                            bugprint = get_reduction_bugprint(current_input_bytes, get_resultprint((traces, statuses, stdouts)), PosixPath(f"reductions/{random.randint(0, 2**32-1)}.reduce.input"))
                            if generation > 0:
                                record_bugprint(current_input, bugprint, len(set(statuses)) == 1)
                            print(
                                color(
                                    Color.green,
                                    f"Bug: {bugprint}",
                                )
                            )
                            if len(set(statuses)) != 1:
                                print(
                                    color(
                                        Color.blue,
                                        f"Exit Status Differential: {str(current_input.resolve())}",
                                    )
                                )
                                for i, status in enumerate(statuses):
                                    print(
                                        color(
                                            Color.red if status else Color.blue,
                                            f"    Exit status {status}:\t{str(TARGET_CONFIGS[i].executable)}",
                                        )
                                    )
                                exit_status_differentials.append(current_input)
                            elif len(set(stdouts)) != 1:
                                print(
                                    color(
                                        Color.yellow,
                                        f"Output differential: {str(current_input.resolve())}",
                                    )
                                )
                                for i, s in enumerate(stdouts):
                                    print(
                                        color(
                                            Color.yellow,
                                            f"    {str(TARGET_CONFIGS[i].executable)} printed\t{s!r}",
                                        )
                                    )
                                output_differentials.append(current_input)
                        else:
                            # We don't mutate exit_status_differentials, even if they're new
                            # print(color(Color.yellow, f"New coverage: {str(current_input.resolve())}"))
                            mutation_candidates.append(current_input)
                    else:
                        # print(color(Color.grey, f"No new coverage: {str(current_input.resolve())}"))
                        rejected_candidates.append(current_input)

                input_queue = []
                while mutation_candidates != [] and len(input_queue) < ROUGH_DESIRED_QUEUE_LEN:
                    for input_to_mutate in mutation_candidates:
                        input_queue.append(mutate_input(input_to_mutate))

                for reject in rejected_candidates:
                    if reject not in SEED_INPUTS:
                        os.remove(reject)

                print(
                    color(
                        Color.green,
                        f"End of generation {generation}.\n"
                        f"Output differentials:\t\t{len(output_differentials)}\n"
                        f"Exit status differentials:\t{len(exit_status_differentials)}\n"
                        f"Mutation candidates:\t\t{len(mutation_candidates)}",
                    )
                )

                generation += 1
            if len(input_queue) == 0:
                termination_reason = "No More Mutation Candidates"
    except (KeyboardInterrupt, AutoTerminationException) as e:
        if isinstance(e, AutoTerminationException):
            termination_reason = "Auto-Termination after " + str(AUTO_TERMINATION) + " seconds"
        else:
            termination_reason = "Keyboard Interrupt"
        pass

    if exit_status_differentials == output_differentials == []:
        print("No differentials found! Try increasing ROUGH_DESIRED_QUEUE_LEN.")
    else:
        if exit_status_differentials != []:
            print(f"Exit status differentials:")
            print("\n".join(str(f.resolve()) for f in exit_status_differentials))
        if output_differentials != []:
            print(f"Output differentials:")
            print("\n".join(str(f.resolve()) for f in output_differentials))

    if BUG_INFO:
        bugprint_summary(len(explored), inputs_run, generation, start_time, termination_reason)



# For pretty printing
class Color(Enum):
    red = 0
    blue = 1
    green = 2
    yellow = 3
    grey = 4
    none = 5


def color(color: Color, s: str):
    COLOR_CODES = {
        Color.red: "\033[0;31m",
        Color.blue: "\033[0;34m",
        Color.green: "\033[0;32m",
        Color.yellow: "\033[0;33m",
        Color.grey: "\033[0;90m",
        Color.none: "\033[0m",
    }
    return COLOR_CODES[color] + s + COLOR_CODES[Color.none]


if __name__ == "__main__":
    main()
