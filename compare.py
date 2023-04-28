from config import *
from pathlib import PosixPath
import sys

def main():
    print(TARGET_CONFIGS[int(sys.argv[1])].executable)

if __name__ == "__main__":
    main()