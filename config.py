#############################################################################################
# config.py
# This is the configuration file for diff_fuzz.py
# Add new targets by adding new entries to TARGET_CONFIGS.
#############################################################################################

from pathlib import PosixPath
from typing import NamedTuple, List, Dict, Optional
import os

# The directory where the seed inputs are
# The seeds are the files from which all the fuzzing inputs are produced,
# so it's important that the seeds are a decently representative sample
# of the inputs accepted by the targets.
SEED_DIR: PosixPath = PosixPath("./seeds")

# Where program traces end up
TRACE_DIR: PosixPath = PosixPath("./traces")

# Time in milliseconds given to each process
TIMEOUT_TIME: int = 100000

# Set this to false if you only care about exit status differentials
# (i.e. the programs you're testing aren't expected to have identical output on stdout)
OUTPUT_DIFFERENTIALS_MATTER: bool = True

# when this is True, a differential is registered if two targets exit with different status codes.
# When it's False, a differential is registered only when one target exits with status 0 and another
# exits with nonzero status.
EXIT_STATUSES_MATTER: bool = False

# Roughly how many processes to allow in a generation (within a factor of 2)
ROUGH_DESIRED_QUEUE_LEN: int = 1000

# full_tree = 0
# valid_tree = 1
# empty_tree = 2
# When this is 0 the set of fundamentals will include minimum urls which are not valid under RFC
# Useful for generating distinct bugprints when parsers accept urls which do not have all the required components
# Instead of classifying these URLs as "" they will match them with errouneous classes like "SOP"
FUNDAMENTAL_TREE_SELECTION: int = 0

# Set to true to allow bug reducer to reduce grammar to minimal compoenents
GRAMMAR_REDUCTIONS: bool = False

# Maximum number of bytes to delete at one time when doing reductions
MAX_BYTES_REDUCTION: int = 4

# Set to -1 to disable auto-termination, otherwise set to the number of seconds to run the process
AUTO_TERMINATION: float = 120

# AFL++ and AFL differ a little about what goes on stdout and what goes on stderr.
# Set this flag if you're using AFL++ so that can be handled correctly.
USES_AFLPLUSPLUS: bool = True

BUG_INFO: bool = True

class TargetConfig(NamedTuple):
    executable: PosixPath  # The path to this target's executable
    cli_args: List[str]  # The CLI arguments this target needs
    needs_qemu: bool  # Whether this executable needs to run in QEMU mode (is a binary that wasn't compiled with afl-cc)
    needs_python_afl: bool  # Whether this executable needs to run with python-afl (is a python script)
    env: Dict[str, str]  # The environment variables to pass to the executable


# Configuration for each fuzzing target
TARGET_CONFIGS: List[TargetConfig] = [
    TargetConfig(
        executable=PosixPath("./targets/urllib_target.py"),
        cli_args=[],
        needs_qemu=False,
        needs_python_afl=True,
        env=dict(os.environ),
    ),
    # TargetConfig(
    #    executable=PosixPath("./targets/urllib3_target.py"),
    #    cli_args=[],
    #    needs_qemu=False,
    #    needs_python_afl=True,
    #    env=dict(os.environ),
    # ),
    # TargetConfig(
    #    executable=PosixPath("./targets/furl_target.py"),
    #    cli_args=[],
    #    needs_qemu=False,
    #    needs_python_afl=True,
    #    env=dict(os.environ),
    # ),
    # TargetConfig(
    #     executable=PosixPath("./targets/yarl_target.py"),
    #     cli_args=[],
    #     needs_qemu=False,
    #     needs_python_afl=True,
    #     env=dict(os.environ),
    # ),
    TargetConfig(
       executable=PosixPath("./targets/rfc3986_target.py"),
       cli_args=[],
       needs_qemu=False,
       needs_python_afl=True,
       env=dict(os.environ),
    ),
    # TargetConfig(
    #    executable=PosixPath("./targets/hyperlink_target.py"),
    #    cli_args=[],
    #    needs_qemu=False,
    #    needs_python_afl=True,
    #    env=dict(os.environ),
    # ),
    # TargetConfig(
    #    executable=PosixPath("./targets/curl/curl_target"),
    #    cli_args=[],
    #    needs_qemu=True,
    #    needs_python_afl=False,
    #    env=dict(os.environ),
    # ),
    # TargetConfig(
    #    executable=PosixPath("./targets/libwget/libwget_target"),
    #    cli_args=[],
    #    needs_qemu=False,
    #    needs_python_afl=False,
    #    env=dict(os.environ),
    # ),
    #    TargetConfig(
    #        executable=PosixPath("./targets/boost_url/boost_url_target"),
    #        cli_args=[],
    #        needs_qemu=False,
    #        needs_python_afl=False,
    #        env=dict(os.environ),
    #    ),
]
