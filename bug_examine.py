from bug_localization import *
from os import listdir
from config import *

def main():
    args = sys.argv[1:]
    dir_name = args[0]
    if not os.path.isdir(dir_name):
        raise ValueError("Not a Directory!")
    bugprint_file = os.path.basename(dir_name)
    BUG_INFO = True
    fundamental_traces = get_fundamental_traces()
    print(f"Bugprint File: {bugprint_file}")
    for file in listdir(dir_name):
        print(f"\n{file}")
        traces_statuses_stdouts = run_executables(PosixPath(f"{dir_name}/{file}"))
        bugprint = get_bugprint(traces_statuses_stdouts[0], fundamental_traces)
        print(f"Bugprint: {bugprint}")

    # # Preprocessing
    # fundamental_traces = get_fundamental_traces()
    # # Runtime
    # print("Running...")
    # traces_statuses_stdouts = run_executables(PosixPath(TEST_INPUT))
    # print("Finding Diff...")
    # bugprint = get_bugprint(traces_statuses_stdouts[0], fundamental_traces)
    # print(f"Bug: {bugprint}")

if __name__ == "__main__":
    main()